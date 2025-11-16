import socket
import mss
import struct
from PIL import Image
import io
import threading
from pynput.mouse import Button, Controller as MouseController

# --- Fonctions pour le serveur ---

def send_screen(client_socket, stop_event):
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
                
                message = struct.pack("L", len(jpeg_bytes)) + jpeg_bytes
                client_socket.sendall(message)
            except (ConnectionResetError, BrokenPipeError):
                print("[!] Le client s'est déconnecté (thread d'envoi).")
                stop_event.set()
                break
            except Exception:
                # Ignorer les erreurs mineures d'envoi pour garder le serveur stable
                stop_event.set()
                break

def receive_commands(client_socket, stop_event):
    """Reçoit et exécute les commandes de contrôle du client."""
    mouse = MouseController()
    data = b""
    payload_size = struct.calcsize("L")

    while not stop_event.is_set():
        try:
            # Lire la taille du message de commande
            while len(data) < payload_size:
                packet = client_socket.recv(4096)
                if not packet: raise ConnectionResetError()
                data += packet
            
            packed_msg_size = data[:payload_size]
            data = data[payload_size:]
            msg_size = struct.unpack("L", packed_msg_size)[0]

            # Lire les données de la commande
            while len(data) < msg_size:
                data += client_socket.recv(4096)
            
            cmd_data = data[:msg_size]
            data = data[msg_size:]
            
            command_str = cmd_data.decode('utf-8')
            
            # --- Exécution de la commande ---
            parts = command_str.split(';')
            cmd_type = parts[0]
            
            if cmd_type == "CLICK":
                x, y, button_name = int(parts[1]), int(parts[2]), parts[3]
                
                # Déplacer la souris
                mouse.position = (x, y)
                
                # Cliquer
                button = Button.left if button_name == "left" else Button.right
                mouse.click(button, 1)
                
                print(f"[*] Clic {button_name} exécuté à ({x}, {y})")

        except (ConnectionResetError, BrokenPipeError):
            print("[!] Le client s'est déconnecté (thread de réception).")
            stop_event.set()
            break
        except Exception as e:
            print(f"[!] Erreur dans le thread de réception : {e}")
            stop_event.set()
            break

def handle_client(client_socket, addr):
    print(f"[*] Connexion acceptée de {addr[0]}:{addr[1]}")
    stop_event = threading.Event()
    
    sender_thread = threading.Thread(target=send_screen, args=(client_socket, stop_event))
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
