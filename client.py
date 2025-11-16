import socket
import tkinter as tk
from PIL import Image, ImageTk
import struct
import io
import threading

# --- Variables globales ---
client_socket = None
root = None
screen_label = None
is_running = True

def receive_frames():
    """
    Reçoit les images JPEG du serveur et les affiche.
    """
    global is_running
    
    data = b""
    payload_size = struct.calcsize("L")

    while is_running:
        try:
            # 1. Lire la taille du message (longueur des données JPEG)
            while len(data) < payload_size:
                packet = client_socket.recv(4 * 1024)
                if not packet: raise ConnectionResetError()
                data += packet
            
            packed_msg_size = data[:payload_size]
            data = data[payload_size:]
            msg_size = struct.unpack("L", packed_msg_size)[0]

            # 2. Lire les données de l'image JPEG
            while len(data) < msg_size:
                data += client_socket.recv(4 * 1024)
            
            frame_data = data[:msg_size]
            data = data[msg_size:]

            # 3. Décompresser l'image JPEG directement depuis la mémoire
            img = Image.open(io.BytesIO(frame_data))
            
            # 4. Convertir pour Tkinter et afficher
            img_tk = ImageTk.PhotoImage(image=img)
            screen_label.config(image=img_tk)
            screen_label.image = img_tk

        except (ConnectionResetError, BrokenPipeError):
            print("[!] La connexion avec le serveur a été perdue.")
            is_running = False
            break
        except Exception as e:
            # Ne pas afficher les erreurs "image file is truncated" qui peuvent arriver
            # si le flux est interrompu au milieu d'une image.
            if "truncated" not in str(e):
                print(f"[!] Erreur lors de la réception : {e}")
            is_running = False
            break
    
    if client_socket:
        client_socket.close()
    if root:
        root.after(100, root.destroy)

def on_closing():
    global is_running
    is_running = False
    print("[*] Fermeture de l'application...")

def start_client():
    global client_socket, root, screen_label

    host = '127.0.0.1'
    port = 9999
    
    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect((host, port))
        print(f"[*] Connecté au serveur sur {host}:{port}")
    except ConnectionRefusedError:
        print("[!] La connexion a été refusée. Le serveur est-il en ligne ?")
        return

    root = tk.Tk()
    root.title("Visionneuse de bureau à distance")
    
    screen_label = tk.Label(root)
    screen_label.pack()

    root.protocol("WM_DELETE_WINDOW", on_closing)

    receive_thread = threading.Thread(target=receive_frames)
    receive_thread.daemon = True
    receive_thread.start()

    root.mainloop()

    is_running = False
    receive_thread.join(timeout=1.0)
    print("[*] Application client terminée.")

if __name__ == "__main__":
    start_client()
