import socket
import tkinter as tk
from PIL import Image, ImageTk
import struct
import io
import threading
import time

# --- Variables globales ---
client_socket = None
root = None
screen_label = None
is_running = True

# --- Fonctions de communication ---

def send_command(command):
    if client_socket and is_running:
        try:
            cmd_bytes = command.encode('utf-8')
            message = struct.pack("L", len(cmd_bytes)) + cmd_bytes
            client_socket.sendall(message)
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass

def connect_and_receive(host, port):
    global is_running, client_socket
    data = b""
    payload_size = struct.calcsize("L")

    while is_running:
        is_connected = False
        while not is_connected and is_running:
            try:
                print(f"[*] Tentative de connexion à {host}:{port}...")
                client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                client_socket.settimeout(3)
                client_socket.connect((host, port))
                client_socket.settimeout(None)
                is_connected = True
                print(f"[*] Connecté au serveur !")
                if root: root.after(0, lambda: screen_label.config(text=""))
            except (ConnectionRefusedError, socket.timeout):
                for i in range(5, -1, -1):
                    if not is_running: break
                    if root:
                        update_text = f"HOSANNA TV+ REGIT FINI non trouvé\nNouvelle tentative dans {i}s..."
                        root.after(0, lambda text=update_text: screen_label.config(text=text, image=''))
                    time.sleep(1)
                if not is_running: break
            except Exception as e:
                print(f"[!] Erreur de connexion : {e}")
                time.sleep(5)

        while is_connected and is_running:
            try:
                # ... (réception des images) ...
                while len(data) < payload_size:
                    packet = client_socket.recv(4 * 1024)
                    if not packet: raise ConnectionResetError()
                    data += packet
                
                packed_msg_size = data[:payload_size]
                data = data[payload_size:]
                msg_size = struct.unpack("L", packed_msg_size)[0]

                while len(data) < msg_size:
                    data += client_socket.recv(4 * 1024)
                
                frame_data = data[:msg_size]
                data = data[msg_size:]

                img = Image.open(io.BytesIO(frame_data))
                img_tk = ImageTk.PhotoImage(image=img)
                screen_label.config(image=img_tk)
                screen_label.image = img_tk
            except (ConnectionResetError, BrokenPipeError):
                print("[!] La connexion avec le serveur a été perdue.")
                is_connected = False
                client_socket.close()
                break
            except Exception:
                is_connected = False
                client_socket.close()
                break

    if client_socket: client_socket.close()
    if root: root.after(100, root.destroy)

# --- Fonctions de l'interface et des événements ---

def handle_mouse_click(event):
    button_name = "left" if event.num == 1 else "right"
    command = f"CLICK;{event.x};{event.y};{button_name}"
    send_command(command)

def handle_mouse_motion(event):
    """Capture le mouvement de la souris et envoie les coordonnées."""
    command = f"MOVE;{event.x};{event.y}"
    send_command(command)

def handle_key_press(event):
    command = f"KEYPRESS;{event.keysym}"
    send_command(command)

def handle_key_release(event):
    command = f"KEYRELEASE;{event.keysym}"
    send_command(command)

def on_closing():
    global is_running
    is_running = False
    print("[*] Fermeture de l'application...")

def start_client():
    global root, screen_label
    host = '127.0.0.1'
    port = 9999
    
    root = tk.Tk()
    root.title("Visionneuse de bureau à distance")
    
    screen_label = tk.Label(root, text="HOSANNA TV+ REGIT FINI non trouvé")
    screen_label.pack(padx=40, pady=40)

    # Lier les événements
    screen_label.bind("<Button-1>", handle_mouse_click)
    screen_label.bind("<Button-3>", handle_mouse_click)
    screen_label.bind("<Motion>", handle_mouse_motion) # NOUVEAU: Mouvement de la souris
    
    root.bind("<KeyPress>", handle_key_press)
    root.bind("<KeyRelease>", handle_key_release)
    
    screen_label.focus_set()

    root.protocol("WM_DELETE_WINDOW", on_closing)

    connect_thread = threading.Thread(target=connect_and_receive, args=(host, port))
    connect_thread.daemon = True
    connect_thread.start()

    root.mainloop()

    is_running = False
    connect_thread.join(timeout=1.0)
    print("[*] Application client terminée.")

if __name__ == "__main__":
    start_client()
