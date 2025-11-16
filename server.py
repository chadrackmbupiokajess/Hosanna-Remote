import socket
import mss
import struct
from PIL import Image
import io

def start_server():
    host = '0.0.0.0'
    port = 9999

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # Permet de réutiliser l'adresse
    server_socket.bind((host, port))
    server_socket.listen(5)
    print(f"[*] Le serveur écoute sur {host}:{port}")

    while True:
        try:
            client_socket, addr = server_socket.accept()
            print(f"[*] Connexion acceptée de {addr[0]}:{addr[1]}")

            with mss.mss() as sct:
                monitor = sct.monitors[1]
                
                while True:
                    # 1. Capture de l'écran
                    sct_img = sct.grab(monitor)
                    
                    # 2. Conversion en image Pillow
                    img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

                    # 3. Compression en JPEG dans un buffer mémoire
                    mem_file = io.BytesIO()
                    # Le paramètre quality (0-95) est un compromis entre qualité et taille.
                    # 75 est un bon point de départ.
                    img.save(mem_file, 'JPEG', quality=75)
                    jpeg_bytes = mem_file.getvalue()
                    
                    # 4. Envoi de la taille puis des données JPEG
                    message = struct.pack("L", len(jpeg_bytes)) + jpeg_bytes
                    client_socket.sendall(message)

        except (ConnectionResetError, BrokenPipeError):
            print("[!] Le client s'est déconnecté.")
        except Exception as e:
            print(f"[!] Erreur : {e}")
            if 'client_socket' in locals():
                client_socket.close()

if __name__ == "__main__":
    start_server()
