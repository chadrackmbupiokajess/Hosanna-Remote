import socket
import mss
import struct
from PIL import Image
import io
import threading
import json
import platform
import os

from pynput.mouse import Button, Controller as MouseController
from pynput.keyboard import Key, Controller as KeyboardController

# --- Fonctions utilitaires ---

def get_system_info():
    """Récupère les informations système de base."""
    try:
        # Tente de trouver l'IP locale en se connectant à un serveur externe
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = 'N/A'
        
    return {
        'os': f"{platform.system()} {platform.release()}",
        'node': platform.node(),
        'user': os.getlogin(),
        'ip': ip
    }

def send_message(sock, lock, msg_type, payload):
    """Fonction centralisée pour envoyer des messages thread-safe."""
    # msg_type: 1-byte pour le type de message
    # payload: les données à envoyer
    message = msg_type + struct.pack("!L", len(payload)) + payload
    with lock:
        sock.sendall(message)

# --- Fonctions de thread pour le serveur ---

def send_screen(client_socket, lock, stop_event):
    """Envoie en continu des captures d'écran au client."""
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        while not stop_event.is_set():
            try:
                sct_img = sct.grab(monitor)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                
                mem_file = io.BytesIO()
                img.save(mem_file, 'JPEG', quality=75)
                jpeg_bytes = mem_file.getvalue()
                
                # Le payload de l'image contient la résolution + les données JPEG
                image_payload = struct.pack("!HH", monitor['width'], monitor['height']) + jpeg_bytes
                
                # Envoi du message de type 'image' (0x01)
                send_message(client_socket, lock, b'\x01', image_payload)
                
            except (ConnectionResetError, BrokenPipeError):
                stop_event.set()
                break
            except Exception:
                stop_event.set()
                break

def get_pynput_key(key_name):
    try:
        return Key[key_name.lower()]
    except KeyError:
        return key_name

def receive_commands(client_socket, stop_event):
    # ... (fonction inchangée)
    mouse = MouseController()
    keyboard = KeyboardController()
    data = b""
    payload_size = struct.calcsize("!L")
    while not stop_event.is_set():
        try:
            while len(data) < payload_size:
                packet = client_socket.recv(4096)
                if not packet: raise ConnectionResetError()
                data += packet
            packed_msg_size = data[:payload_size]
            data = data[payload_size:]
            msg_size = struct.unpack("!L", packed_msg_size)[0]
            while len(data) < msg_size:
                data += client_socket.recv(4096)
            cmd_data = data[:msg_size]
            data = data[msg_size:]
            command_str = cmd_data.decode('utf-8')
            parts = command_str.split(';')
            cmd_type = parts[0]
            if cmd_type == "CLICK":
                x, y, button_name = int(parts[1]), int(parts[2]), parts[3]
                mouse.position = (x, y)
                button = Button.left if button_name == "left" else Button.right
                mouse.click(button, 1)
            elif cmd_type == "MOVE":
                x, y = int(parts[1]), int(parts[2])
                mouse.position = (x, y)
            elif cmd_type == "KEYPRESS":
                key_name = parts[1]
                key = get_pynput_key(key_name)
                keyboard.press(key)
            elif cmd_type == "KEYRELEASE":
                key_name = parts[1]
                key = get_pynput_key(key_name)
                keyboard.release(key)
        except (ConnectionResetError, BrokenPipeError):
            stop_event.set()
            break
        except Exception:
            pass

def handle_client(client_socket, addr):
    print(f"[*] Connexion acceptée de {addr[0]}:{addr[1]}")
    stop_event = threading.Event()
    send_lock = threading.Lock() # Verrou pour synchroniser les envois

    # --- Envoyer les informations système au client ---
    sys_info = get_system_info()
    info_payload = json.dumps(sys_info).encode('utf-8')
    # Envoi du message de type 'info' (0x02)
    send_message(client_socket, send_lock, b'\x02', info_payload)
    print(f"[*] Informations système envoyées : {sys_info}")
    # -------------------------------------------------
    
    sender_thread = threading.Thread(target=send_screen, args=(client_socket, send_lock, stop_event))
    receiver_thread = threading.Thread(target=receive_commands, args=(client_socket, stop_event))
    
    sender_thread.daemon = True
    receiver_thread.daemon = True
    
    sender_thread.start()
    receiver_thread.start()
    
    sender_thread.join()
    receiver_thread.join()
    
    print(f"[*] Connexion avec {addr[0]} terminée.")
    client_socket.close()

def start_server():
    # ... (fonction inchangée)
    host = '0.0.0.0'
    port = 9999
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(5)
    print(f"[*] Le serveur écoute sur {host}:{port}")
    while True:
        try:
            client_socket, addr = server_socket.accept()
            client_handler_thread = threading.Thread(target=handle_client, args=(client_socket, addr))
            client_handler_thread.daemon = True
            client_handler_thread.start()
        except KeyboardInterrupt:
            print("\n[*] Arrêt du serveur.")
            break
        except Exception as e:
            print(f"[!] Erreur du serveur principal : {e}")
            break
    server_socket.close()

if __name__ == "__main__":
    start_server()
