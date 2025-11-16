import socket
import struct
import io
import threading
import time
from PIL import Image as PilImage

# --- Kivy Imports ---
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image as KivyImage
from kivy.uix.label import Label
from kivy.graphics.texture import Texture
from kivy.clock import Clock
from kivy.core.window import Window

# --- Variables globales ---
is_running = True

class RemoteViewerLayout(BoxLayout):
    """Widget principal de l'application Kivy."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        
        self.status_label = Label(
            text="Lancement de la visionneuse...",
            size_hint_y=None,
            height=30,
            font_size='15sp'
        )
        
        self.screen_image = KivyImage(
            allow_stretch=True,
            keep_ratio=True
        )
        
        self.add_widget(self.status_label)
        self.add_widget(self.screen_image)

    def update_image(self, jpeg_data):
        """Met à jour la texture de l'image à partir des données JPEG."""
        try:
            buf = io.BytesIO(jpeg_data)
            img = PilImage.open(buf)
            
            texture = Texture.create(size=img.size)
            texture.blit_buffer(img.tobytes(), colorfmt='rgb', bufferfmt='ubyte')
            texture.flip_vertical()
            
            self.screen_image.texture = texture
        except Exception as e:
            print(f"[!] Erreur de mise à jour de l'image: {e}")

    def update_status(self, text):
        """Met à jour le texte du label de statut."""
        self.status_label.text = text


class RemoteViewerApp(App):
    def build(self):
        self.title = "Hosanna Remote Viewer"
        self.layout = RemoteViewerLayout()
        return self.layout

    def on_start(self):
        host = '127.0.0.1'
        port = 9999
        
        connect_thread = threading.Thread(target=self.connect_and_receive, args=(host, port))
        connect_thread.daemon = True
        connect_thread.start()

    def on_stop(self):
        global is_running
        is_running = False

    def connect_and_receive(self, host, port):
        """Gère la connexion, la reconnexion et la réception des données."""
        client_socket = None
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
                    Clock.schedule_once(lambda dt: self.layout.update_status("Connecté"))
                except (ConnectionRefusedError, socket.timeout):
                    for i in range(5, -1, -1):
                        if not is_running: break
                        update_text = f"HOSANNA TV+ REGIT FINI non trouvé (Nouvelle tentative dans {i}s...)"
                        Clock.schedule_once(lambda dt, text=update_text: self.layout.update_status(text))
                        time.sleep(1)
                    if not is_running: break
                except Exception as e:
                    print(f"[!] Erreur de connexion : {e}")
                    time.sleep(5)

            while is_connected and is_running:
                try:
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
                    
                    Clock.schedule_once(lambda dt, frame=frame_data: self.layout.update_image(frame))

                except (ConnectionResetError, BrokenPipeError):
                    print("[!] La connexion avec le serveur a été perdue.")
                    is_connected = False
                    if client_socket: client_socket.close()
                    # Correction de l'erreur de syntaxe ici
                    Clock.schedule_once(lambda dt: setattr(self.layout.screen_image, 'texture', None))
                    break
                except Exception:
                    is_connected = False
                    if client_socket: client_socket.close()
                    break
        
        if client_socket: client_socket.close()

if __name__ == "__main__":
    RemoteViewerApp().run()
