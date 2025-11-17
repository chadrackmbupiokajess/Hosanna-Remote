import socket
import mss
import struct
from PIL import Image
import io
import threading
import json
import platform
import os
import time
import psutil
import re
import cpuinfo
import ssl
import sys
import tkinter as tk
from tkinter import scrolledtext, messagebox, font
from queue import Queue

from pynput.mouse import Button, Controller as MouseController
from pynput.keyboard import Key, Controller as KeyboardController

# --- Constantes ---
DISCOVERY_PORT = 1982 # Port pour la découverte UDP
SERVER_PORT = 1981    # Port pour la connexion TCP sécurisée
# ------------------

# --- Queues pour la communication inter-threads ---
message_to_gui_queue = Queue()
message_from_gui_queue = Queue() # Contient (message, client_addr)
# -------------------------------------------------

# --- Fonctions utilitaires ---

def bytes_to_gb(bytes_val):
    return round(bytes_val / (1024**3), 1)

def parse_cpu_name(raw_name):
    match = re.search(r'(i[3579])[- ]?(\d{1,2})\d{2,}', raw_name)
    if match:
        brand = match.group(1).upper()
        gen_str = match.group(2)
        if gen_str.endswith('1') and gen_str != '11': suffix = 'st'
        elif gen_str.endswith('2') and gen_str != '12': suffix = 'nd'
        elif gen_str.endswith('3') and gen_str != '13': suffix = 'rd'
        else: suffix = 'th'
        return f"Intel Core {brand} ({gen_str}{suffix} Gen)"
    
    clean_name = raw_name.replace("(R)", "").replace("(TM)", "").replace("CPU", "").strip()
    clean_name = re.sub(r'@ \d+\.\d+GHz', '', clean_name).strip()
    if 'Family' in clean_name and 'Model' in clean_name:
        if 'Intel' in clean_name: return 'Intel Processor'
        if 'AMD' in clean_name: return 'AMD Processor'
    return " ".join(clean_name.split())

def get_system_info():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = 'N/A'
    
    cpu_freq_str = "N/A"
    try:
        freq = psutil.cpu_freq()
        cpu_freq_str = f"{freq.current / 1000:.2f} GHz (Max: {freq.max / 1000:.2f} GHz)"
    except Exception:
        pass

    try:
        cpu_brand_raw = cpuinfo.get_cpu_info()['brand_raw']
        cpu_name = parse_cpu_name(cpu_brand_raw)
    except Exception:
        cpu_name = parse_cpu_name(platform.processor())

    arch = platform.architecture()[0]
    arch_str = "x64" if '64' in arch else "x86"
    final_cpu_name = f"{cpu_name} ({arch_str})"

    return {
        'os': f"{platform.system()} {platform.release()}",
        'node': platform.node(),
        'user': os.getlogin(),
        'ip': ip,
        'cpu_info': final_cpu_name,
        'cpu_freq': cpu_freq_str,
        'ram_total': f"{bytes_to_gb(psutil.virtual_memory().total)} Go",
        'disk_total_static': f"{bytes_to_gb(psutil.disk_usage('/').total)} Go"
    }

def get_realtime_stats():
    disk = psutil.disk_usage('/')
    return {
        'cpu_percent': psutil.cpu_percent(interval=None),
        'ram_percent': psutil.virtual_memory().percent,
        'disk_percent': disk.percent,
        'disk_used': disk.used,
        'disk_total': disk.total
    }

def send_message(sock, lock, msg_type, payload):
    message = msg_type + struct.pack("!L", len(payload)) + payload
    with lock:
        sock.sendall(message)


# --- Fonctions de thread ---

def send_screen(client_socket, lock, stop_event):
    print(f"[*] SERVER THREAD send_screen: Démarré.") # DEBUG
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        while not stop_event.is_set():
            try:
                sct_img = sct.grab(monitor)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                mem_file = io.BytesIO()
                img.save(mem_file, 'JPEG', quality=75)
                jpeg_bytes = mem_file.getvalue()
                image_payload = struct.pack("!HH", monitor['width'], monitor['height']) + jpeg_bytes
                send_message(client_socket, lock, b'\x01', image_payload)
            except (ConnectionResetError, BrokenPipeError): stop_event.set(); break
            except Exception as e: print(f"Erreur dans send_screen: {e}"); stop_event.set(); break
    print(f"[*] SERVER THREAD send_screen: Arrêté.") # DEBUG

def send_stats(client_socket, lock, stop_event):
    print(f"[*] SERVER THREAD send_stats: Démarré.") # DEBUG
    psutil.cpu_percent(interval=None)
    while not stop_event.is_set():
        try:
            stats = get_realtime_stats()
            stats_payload = json.dumps(stats).encode('utf-8')
            send_message(client_socket, lock, b'\x03', stats_payload)
            time.sleep(1)
        except (ConnectionResetError, BrokenPipeError): stop_event.set(); break
        except Exception as e: print(f"Erreur dans send_stats: {e}"); stop_event.set(); break
    print(f"[*] SERVER THREAD send_stats: Arrêté.") # DEBUG

def get_pynput_key(key_name):
    try: return Key[key_name.lower()]
    except KeyError: return key_name

def receive_commands(client_socket, lock, stop_event, client_addr):
    print(f"[*] SERVER THREAD receive_commands: Démarré.") # DEBUG
    mouse, keyboard = MouseController(), KeyboardController()
    data = b""
    header_size = struct.calcsize("!L") + 1
    while not stop_event.is_set():
        try:
            while len(data) < header_size:
                packet = client_socket.recv(4096)
                if not packet: raise ConnectionResetError()
                data += packet
            
            msg_type, msg_size = data[0:1], struct.unpack("!L", data[1:header_size])[0]
            data = data[header_size:]

            while len(data) < msg_size: data += client_socket.recv(4096)
            
            payload = data[:msg_size]
            data = data[msg_size:]

            if msg_type == b'\x00':
                command_str = payload.decode('utf-8')
                parts = command_str.split(';')
                cmd_type = parts[0]
                
                if cmd_type == "CLICK":
                    x, y, btn = int(parts[1]), int(parts[2]), parts[3]
                    mouse.position = (x, y)
                    mouse.click(Button.left if btn == "left" else Button.right, 1)
                    print(f"[*] SERVER: CLICK received at ({x}, {y}) with button {btn}") # DEBUG
                elif cmd_type == "MOVE":
                    x, y = int(parts[1]), int(parts[2])
                    mouse.position = (x, y)
                elif cmd_type == "KEYPRESS":
                    keyboard.press(get_pynput_key(parts[1]))
                    print(f"[*] SERVER: KEYPRESS received for {parts[1]}") # DEBUG
                elif cmd_type == "KEYRELEASE":
                    keyboard.release(get_pynput_key(parts[1]))
                    print(f"[*] SERVER: KEYRELEASE received for {parts[1]}") # DEBUG
            
            elif msg_type == b'\x04': # Message du client
                client_message = payload.decode('utf-8')
                print(f"[MESSAGE DU CLIENT]: {client_message}")
                message_to_gui_queue.put((client_message, client_addr))
            
        except (ConnectionResetError, BrokenPipeError): stop_event.set(); break
        except Exception as e: print(f"Erreur dans receive_commands: {e}"); stop_event.set(); break
    print(f"[*] SERVER THREAD receive_commands: Arrêté.") # DEBUG

def handle_client(client_socket, addr, stop_event):
    print(f"[*] SERVER: Connexion sécurisée acceptée de {addr[0]}:{addr[1]}") # DEBUG
    send_lock = threading.Lock()
    try:
        sys_info = get_system_info()
        info_payload = json.dumps(sys_info).encode('utf-8')
        send_message(client_socket, send_lock, b'\x02', info_payload)
        print(f"[*] SERVER: Infos système initiales envoyées à {addr[0]}") # DEBUG
    except Exception as e:
        print(f"[!] SERVER: Erreur critique lors de l'envoi des infos système initiales à {addr[0]}: {e}") # DEBUG
        client_socket.close()
        return

    threads = [
        threading.Thread(target=send_screen, args=(client_socket, send_lock, stop_event)),
        threading.Thread(target=send_stats, args=(client_socket, send_lock, stop_event)),
        threading.Thread(target=receive_commands, args=(client_socket, send_lock, stop_event, addr))
    ]
    for t in threads:
        t.daemon = True
        t.start()
    print(f"[*] SERVER: Threads de communication démarrés pour {addr[0]}") # DEBUG

    def send_gui_replies():
        while not stop_event.is_set():
            try:
                server_reply, target_client_addr = message_from_gui_queue.get(timeout=0.1)
                if target_client_addr == addr:
                    print(f"[*] SERVER: Envoi de la réponse GUI au client {target_client_addr}: {server_reply}")
                    send_message(client_socket, send_lock, b'\x05', server_reply.encode('utf-8'))
            except Exception:
                pass
    
    reply_thread = threading.Thread(target=send_gui_replies)
    reply_thread.daemon = True
    reply_thread.start()
    threads.append(reply_thread)

    for t in threads:
        t.join()
    print(f"[*] SERVER: Connexion avec {addr[0]} terminée. Fermeture du socket.") # DEBUG
    client_socket.close()

# --- NOUVEAU: Fonction pour la fenêtre de messagerie Tkinter ---
def start_server_message_gui(stop_event):
    root = tk.Tk()
    root.withdraw()

    message_window = None
    message_text_widget = None
    reply_entry = None
    current_client_addr = None

    def send_reply_and_close(reply_text_from_entry):
        nonlocal current_client_addr
        if reply_text_from_entry:
            message_from_gui_queue.put((reply_text_from_entry, current_client_addr))
        else:
            message_from_gui_queue.put(("Serveur: Votre message a été ignoré.", current_client_addr))
        
        if message_window and message_window.winfo_exists():
            message_window.destroy()
        current_client_addr = None

    def on_close_window(event=None):
        if message_window and message_window.winfo_exists():
            send_reply_and_close("")

    def show_message_window_callback(client_msg, client_addr):
        nonlocal message_window, message_text_widget, reply_entry, current_client_addr
        current_client_addr = client_addr

        if message_window is None or not message_window.winfo_exists():
            message_window = tk.Toplevel(root)
            message_window.title(f"Message du Client ({client_addr[0]})")
            
            # CORRECTION: Agrandir la fenêtre
            window_width = 800
            window_height = 600
            
            screen_width = message_window.winfo_screenwidth()
            screen_height = message_window.winfo_screenheight()
            center_x = int(screen_width/2 - window_width / 2)
            center_y = int(screen_height/2 - window_height / 2)
            message_window.geometry(f"{window_width}x{window_height}+{center_x}+{center_y}")

            message_window.attributes('-topmost', True)
            
            message_window.protocol("WM_DELETE_WINDOW", on_close_window)

            message_frame = tk.Frame(message_window)
            message_frame.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

            # CORRECTION: Augmenter la taille de la police
            default_font = font.nametofont("TkDefaultFont")
            default_font.configure(size=14)
            
            message_text_widget = scrolledtext.ScrolledText(message_frame, wrap=tk.WORD, state='disabled', height=8, font=default_font)
            message_text_widget.pack(fill=tk.BOTH, expand=True)

            reply_entry = tk.Entry(message_frame, width=40, font=default_font)
            reply_entry.pack(pady=5, fill=tk.X)
            reply_entry.bind("<Return>", lambda event: send_reply_and_close(reply_entry.get().strip()))

            send_button = tk.Button(message_frame, text="Répondre", command=lambda: send_reply_and_close(reply_entry.get().strip()), font=default_font)
            send_button.pack(side=tk.LEFT, padx=5, pady=5)

            close_button = tk.Button(message_frame, text="Fermer", command=on_close_window, font=default_font)
            close_button.pack(side=tk.RIGHT, padx=5, pady=5)
            
        message_text_widget.config(state='normal')
        message_text_widget.insert(tk.END, f"Client ({client_addr[0]}): {client_msg}\n")
        message_text_widget.config(state='disabled')
        message_text_widget.see(tk.END)
        message_window.deiconify()
        message_window.lift()
        message_window.focus_force()

    def check_queue():
        try:
            client_msg, client_addr = message_to_gui_queue.get_nowait()
            show_message_window_callback(client_msg, client_addr)
        except Exception:
            pass
        if not stop_event.is_set():
            root.after(100, check_queue)
        else:
            root.quit()

    root.after(100, check_queue)
    root.mainloop()
    print("[*] Thread GUI Tkinter arrêté.")

# --- NOUVEAU: Fonction de broadcast UDP pour la découverte ---
def discovery_broadcast(server_ip, server_port, stop_event):
    broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    broadcast_socket.settimeout(1) # Petit timeout pour vérifier stop_event

    message = f"HOSANNA_REMOTE_SERVER_ADVERTISEMENT;{server_ip};{server_port}".encode('utf-8')
    print(f"[*] Démarrage du broadcast de découverte sur le port {DISCOVERY_PORT}...")

    while not stop_event.is_set():
        try:
            broadcast_socket.sendto(message, ('<broadcast>', DISCOVERY_PORT))
            # print(f"[*] Broadcast envoyé: {message.decode()}")
        except Exception as e:
            print(f"[!] Erreur lors de l'envoi du broadcast: {e}")
        time.sleep(3) # Envoyer toutes les 3 secondes
    
    broadcast_socket.close()
    print("[*] Arrêt du broadcast de découverte.")

# --- Fonction de démarrage du serveur en mode application ---
def start_server():
    host = '0.0.0.0'
    port = SERVER_PORT

    # Détecter si nous sommes dans un bundle PyInstaller
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))

    cert_file_path = os.path.join(base_path, "cert.pem")
    key_file_path = os.path.join(base_path, "key.pem")

    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    try:
        context.load_cert_chain(certfile=cert_file_path, keyfile=key_file_path)
    except FileNotFoundError:
        print(f"Erreur: cert.pem ou key.pem non trouvé à {base_path}. Le serveur ne peut pas démarrer.")
        return
    except Exception as e:
        print(f"Erreur de chargement des certificats SSL: {e}")
        return

    # Obtenir l'IP locale du serveur pour le broadcast
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "127.0.0.1" # Fallback si pas de connexion internet

    server_stop_event = threading.Event()

    # Démarrer le thread de broadcast de découverte
    discovery_thread = threading.Thread(target=discovery_broadcast, args=(local_ip, port, server_stop_event))
    discovery_thread.daemon = True
    discovery_thread.start()

    # NOUVEAU: Démarrer le thread GUI de messagerie
    gui_thread = threading.Thread(target=start_server_message_gui, args=(server_stop_event,))
    gui_thread.daemon = True
    gui_thread.start()

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
            sock.listen(5)
            print(f"[*] Le serveur sécurisé écoute sur {host}:{port} en mode application.")
            
            with context.wrap_socket(sock, server_side=True) as ssock:
                while not server_stop_event.is_set(): # Utiliser le même stop_event
                    try:
                        ssock.settimeout(1) 
                        client_socket, addr = ssock.accept()
                        stop_event_client = threading.Event() # Stop event par client
                        threading.Thread(target=handle_client, args=(client_socket, addr, stop_event_client), daemon=True).start()
                    except socket.timeout:
                        pass
                    except KeyboardInterrupt:
                        print("\n[*] Arrêt du serveur.")
                        server_stop_event.set() # Signaler l'arrêt
                        break
                    except Exception as e:
                        print(f"[!] Erreur dans la boucle principale du serveur: {e}")
    except Exception as e:
        print(f"[!] Erreur critique lors du démarrage du socket serveur: {e}")
        server_stop_event.set() # Signaler l'arrêt en cas d'erreur critique

    # Attendre la fin des threads
    if discovery_thread and discovery_thread.is_alive():
        discovery_thread.join(timeout=5)
    if gui_thread and gui_thread.is_alive():
        gui_thread.join(timeout=5)
    print("[*] Serveur arrêté.")


# --- Bloc d'exécution principal ---
if __name__ == '__main__':
    # NOUVEAU: Supprimer le fichier batch pour éviter les confusions
    if os.path.exists("install_and_start_service.bat"):
        os.remove("install_and_start_service.bat")
        print("Fichier install_and_start_service.bat supprimé.")
    
    # NOUVEAU: Supprimer le fichier de log du service
    if os.path.exists("server_service.log"):
        os.remove("server_service.log")
        print("Fichier server_service.log supprimé.")

    start_server()
