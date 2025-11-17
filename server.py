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
from queue import Queue, Empty

from pynput.mouse import Button, Controller as MouseController
from pynput.keyboard import Key, Controller as KeyboardController

# --- Constantes ---
DISCOVERY_PORT = 1982 # Port pour la découverte UDP
SERVER_PORT = 1981    # Port pour la connexion TCP sécurisée
# ------------------

# --- Queues pour la communication inter-threads ---
message_to_gui_queue = Queue()
message_from_gui_queue = Queue() # Contient (message, client_addr)
command_queue = Queue() # Pour les commandes client (souris/clavier)
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

def send_stats(client_socket, lock, stop_event):
    psutil.cpu_percent(interval=None)
    while not stop_event.is_set():
        try:
            stats = get_realtime_stats()
            stats_payload = json.dumps(stats).encode('utf-8')
            send_message(client_socket, lock, b'\x03', stats_payload)
            time.sleep(1)
        except (ConnectionResetError, BrokenPipeError): stop_event.set(); break
        except Exception as e: print(f"Erreur dans send_stats: {e}"); stop_event.set(); break

# CORRIGÉ: Dictionnaire de mapping COMPLET pour les touches spéciales
KIVY_TO_PYNPUT_MAP = {
    'spacebar': 'space',
    'lctrl': 'ctrl_l',
    'rctrl': 'ctrl_r',
    'ctrl': 'ctrl',
    'lalt': 'alt_l',
    'ralt': 'alt_gr',
    'alt': 'alt',
    'lshift': 'shift_l',
    'rshift': 'shift_r',
    'shift': 'shift',
    'capslock': 'caps_lock',
    'escape': 'esc',
    'pageup': 'page_up',
    'pagedown': 'page_down',
    'enter': 'enter',
    'backspace': 'backspace',
    'tab': 'tab',
    'delete': 'delete',
    'home': 'home',
    'end': 'end',
    'insert': 'insert',
    'numlock': 'num_lock',
    'printscreen': 'print_screen',
    'scrolllock': 'scroll_lock',
    'pause': 'pause',
    'up': 'up',
    'down': 'down',
    'left': 'left',
    'right': 'right',
}

def get_pynput_key(key_name):
    pynput_name = KIVY_TO_PYNPUT_MAP.get(key_name, key_name)
    try:
        return Key[pynput_name]
    except KeyError:
        return pynput_name

# Thread pour traiter les commandes de manière centralisée
def command_processor(stop_event):
    print(f"[*] Thread processeur de commandes démarré.")
    mouse, keyboard = MouseController(), KeyboardController()
    while not stop_event.is_set():
        try:
            cmd_type, args = command_queue.get(timeout=0.1)

            if cmd_type == "MOUSEDOWN":
                x, y, btn = args
                mouse.position = (x, y)
                mouse.press(Button.left if btn == "left" else Button.right)
            elif cmd_type == "MOUSEUP":
                x, y, btn = args
                mouse.position = (x, y)
                mouse.release(Button.left if btn == "left" else Button.right)
            elif cmd_type == "CLICK":
                x, y, btn = args
                mouse.position = (x, y)
                mouse.click(Button.left if btn == "left" else Button.right, 1)
            elif cmd_type == "DOUBLECLICK":
                x, y, btn = args
                mouse.position = (x, y)
                mouse.click(Button.left if btn == "left" else Button.right, 2)
            elif cmd_type == "MOVE":
                x, y = args
                mouse.position = (x, y)
            elif cmd_type == "KEYPRESS":
                key_str = args[0]
                keyboard.press(get_pynput_key(key_str))
            elif cmd_type == "KEYRELEASE":
                key_str = args[0]
                keyboard.release(get_pynput_key(key_str))
        except Empty:
            continue
        except Exception as e:
            print(f"[!] Erreur dans command_processor: {e} pour la commande {cmd_type} avec args {args}")
    print(f"[*] Thread processeur de commandes arrêté.")

# Ce thread ne fait que recevoir et mettre en file d'attente
def receive_commands(client_socket, stop_event, client_addr):
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

            if msg_type == b'\x00': # Commande
                command_str = payload.decode('utf-8')
                parts = command_str.split(';')
                cmd_type = parts[0]
                
                if cmd_type in ["MOUSEDOWN", "MOUSEUP", "CLICK", "DOUBLECLICK"]:
                    args = (int(parts[1]), int(parts[2]), parts[3])
                    command_queue.put((cmd_type, args))
                elif cmd_type == "MOVE":
                    args = (int(parts[1]), int(parts[2]))
                    command_queue.put((cmd_type, args))
                elif cmd_type in ["KEYPRESS", "KEYRELEASE"]:
                    args = (parts[1],) 
                    command_queue.put((cmd_type, args))
            
            elif msg_type == b'\x04': # Message du client
                client_message = payload.decode('utf-8')
                message_to_gui_queue.put((client_message, client_addr))
            
        except (ConnectionResetError, BrokenPipeError): stop_event.set(); break
        except Exception as e: print(f"Erreur dans receive_commands: {e}"); stop_event.set(); break

def handle_client(client_socket, addr, stop_event):
    print(f"[*] Connexion sécurisée acceptée de {addr[0]}:{addr[1]}")
    send_lock = threading.Lock()
    try:
        sys_info = get_system_info()
        info_payload = json.dumps(sys_info).encode('utf-8')
        send_message(client_socket, send_lock, b'\x02', info_payload)
    except Exception as e:
        print(f"[!] Erreur critique lors de l'envoi des infos système initiales à {addr[0]}: {e}")
        client_socket.close()
        return

    threads = [
        threading.Thread(target=send_screen, args=(client_socket, send_lock, stop_event)),
        threading.Thread(target=send_stats, args=(client_socket, send_lock, stop_event)),
        threading.Thread(target=receive_commands, args=(client_socket, stop_event, addr))
    ]
    for t in threads:
        t.daemon = True
        t.start()

    def send_gui_replies():
        while not stop_event.is_set():
            try:
                server_reply, target_client_addr = message_from_gui_queue.get(timeout=0.1)
                if target_client_addr == addr:
                    send_message(client_socket, send_lock, b'\x05', server_reply.encode('utf-8'))
            except Empty:
                pass
            except Exception as e:
                print(f"Erreur dans send_gui_replies: {e}")
    
    reply_thread = threading.Thread(target=send_gui_replies)
    reply_thread.daemon = True
    reply_thread.start()
    threads.append(reply_thread)

    for t in threads:
        t.join()
    print(f"[*] Connexion avec {addr[0]} terminée. Fermeture du socket.")
    client_socket.close()

# --- Fonction pour la fenêtre de messagerie Tkinter ---
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
            message_window.overrideredirect(True)
            
            window_width, window_height = 800, 600
            screen_width, screen_height = message_window.winfo_screenwidth(), message_window.winfo_screenheight()
            center_x, center_y = int(screen_width/2 - window_width/2), int(screen_height/2 - window_height/2)
            message_window.geometry(f"{window_width}x{window_height}+{center_x}+{center_y}")

            message_window.attributes('-topmost', True)
            message_window.protocol("WM_DELETE_WINDOW", on_close_window)

            message_frame = tk.Frame(message_window, borderwidth=0)
            message_frame.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

            default_font = font.nametofont("TkDefaultFont")
            default_font.configure(size=14)
            bold_font = font.Font(family=default_font['family'], size=default_font['size'], weight='bold')
            
            message_text_widget = scrolledtext.ScrolledText(message_frame, wrap=tk.WORD, state='disabled', height=8, font=default_font)
            message_text_widget.tag_configure('bold', font=bold_font)
            message_text_widget.pack(fill=tk.BOTH, expand=True)

            reply_entry = tk.Entry(message_frame, width=40, font=default_font)
            reply_entry.pack(pady=5, fill=tk.X)
            reply_entry.bind("<Return>", lambda event: send_reply_and_close(reply_entry.get().strip()))

            send_button = tk.Button(message_frame, text="Répondre", command=lambda: send_reply_and_close(reply_entry.get().strip()), font=default_font)
            send_button.pack(side=tk.LEFT, padx=5, pady=5)

            close_button = tk.Button(message_frame, text="Fermer", command=on_close_window, font=default_font)
            close_button.pack(side=tk.RIGHT, padx=5, pady=5)
            
        message_text_widget.config(state='normal')
        message_text_widget.insert(tk.END, "Hosanna Tv+ Régit: ", 'bold')
        message_text_widget.insert(tk.END, f"{client_msg}\n")
        message_text_widget.config(state='disabled')
        message_text_widget.see(tk.END)
        message_window.deiconify()
        message_window.lift()
        message_window.focus_force()

    def check_queue():
        try:
            client_msg, client_addr = message_to_gui_queue.get_nowait()
            show_message_window_callback(client_msg, client_addr)
        except Empty:
            pass
        except Exception as e:
            print(f"Erreur dans check_queue (GUI): {e}")

        if not stop_event.is_set():
            root.after(100, check_queue)
        else:
            root.quit()

    root.after(100, check_queue)
    root.mainloop()
    print("[*] Thread GUI Tkinter arrêté.")

# --- Fonction de broadcast UDP pour la découverte ---
def discovery_broadcast(server_ip, server_port, stop_event):
    broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    broadcast_socket.settimeout(1)

    message = f"HOSANNA_REMOTE_SERVER_ADVERTISEMENT;{server_ip};{server_port}".encode('utf-8')
    print(f"[*] Démarrage du broadcast de découverte sur le port {DISCOVERY_PORT}...")

    while not stop_event.is_set():
        try:
            broadcast_socket.sendto(message, ('<broadcast>', DISCOVERY_PORT))
        except Exception as e:
            print(f"[!] Erreur lors de l'envoi du broadcast: {e}")
        time.sleep(3)
    
    broadcast_socket.close()
    print("[*] Arrêt du broadcast de découverte.")

# --- Fonction de démarrage du serveur en mode application ---
def start_server():
    host = '0.0.0.0'
    port = SERVER_PORT

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

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "127.0.0.1"

    server_stop_event = threading.Event()

    global_threads = [
        threading.Thread(target=discovery_broadcast, args=(local_ip, port, server_stop_event)),
        threading.Thread(target=start_server_message_gui, args=(server_stop_event,)),
        threading.Thread(target=command_processor, args=(server_stop_event,))
    ]

    for t in global_threads:
        t.daemon = True
        t.start()

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
            sock.listen(5)
            print(f"[*] Le serveur sécurisé écoute sur {host}:{port} en mode application.")
            
            with context.wrap_socket(sock, server_side=True) as ssock:
                while not server_stop_event.is_set():
                    try:
                        ssock.settimeout(1) 
                        client_socket, addr = ssock.accept()
                        stop_event_client = threading.Event()
                        threading.Thread(target=handle_client, args=(client_socket, addr, stop_event_client), daemon=True).start()
                    except socket.timeout:
                        pass
                    except KeyboardInterrupt:
                        print("\n[*] Arrêt du serveur.")
                        server_stop_event.set()
                        break
                    except Exception as e:
                        print(f"[!] Erreur dans la boucle principale du serveur: {e}")
    except Exception as e:
        print(f"[!] Erreur critique lors du démarrage du socket serveur: {e}")
        server_stop_event.set()

    for t in global_threads:
        if t.is_alive():
            t.join(timeout=2)
    print("[*] Serveur arrêté.")


# --- Bloc d'exécution principal ---
if __name__ == '__main__':
    if os.path.exists("install_and_start_service.bat"):
        os.remove("install_and_start_service.bat")
        print("Fichier install_and_start_service.bat supprimé.")
    
    if os.path.exists("server_service.log"):
        os.remove("server_service.log")
        print("Fichier server_service.log supprimé.")

    start_server()
