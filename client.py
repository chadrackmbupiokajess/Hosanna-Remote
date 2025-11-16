import socket
import struct
import io
import threading
import time
from PIL import Image as PilImage

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image as KivyImage
from kivy.uix.label import Label
from kivy.graphics.texture import Texture
from kivy.clock import Clock
from kivy.core.window import Window

is_running = True
client_socket = None

def send_command(command):
    if client_socket and is_running:
        try:
            cmd_bytes = command.encode('utf-8')
            message = struct.pack("!L", len(cmd_bytes)) + cmd_bytes
            client_socket.sendall(message)
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass

class RemoteViewerLayout(BoxLayout):
    # ... (classe inchangée)
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.server_resolution = (1, 1)
        self.status_label = Label(text="Lancement...", size_hint_y=None, height=30, font_size='15sp')
        self.screen_image = KivyImage(allow_stretch=True, keep_ratio=True)
        self.add_widget(self.status_label)
        self.add_widget(self.screen_image)

    def update_image(self, jpeg_data):
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
        self.status_label.text = text

    def _get_scaled_coords(self, touch):
        img = self.screen_image
        touch_x = touch.x - img.x
        touch_y = touch.y - img.y
        img_width, img_height = img.norm_image_size
        ratio_x = self.server_resolution[0] / img_width
        ratio_y = self.server_resolution[1] / img_height
        server_x = int(touch_x * ratio_x)
        server_y = int((img_height - touch_y) * ratio_y)
        return server_x, server_y

    def on_touch_down(self, touch):
        if self.screen_image.collide_point(*touch.pos):
            server_x, server_y = self._get_scaled_coords(touch)
            button_name = "left" if touch.button == 'left' else "right"
            command = f"CLICK;{server_x};{server_y};{button_name}"
            send_command(command)
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self.screen_image.collide_point(*touch.pos):
            server_x, server_y = self._get_scaled_coords(touch)
            command = f"MOVE;{server_x};{server_y}"
            send_command(command)
            return True
        return super().on_touch_move(touch)

class RemoteViewerApp(App):
    def build(self):
        self.title = "Hosanna Remote Viewer"
        self.layout = RemoteViewerLayout()
        # NOUVEAU: Demander le contrôle du clavier
        self._keyboard = Window.request_keyboard(self._keyboard_closed, self.root)
        self._keyboard.bind(on_key_down=self._on_key_down)
        self._keyboard.bind(on_key_up=self._on_key_up)
        return self.layout

    # --- NOUVELLES FONCTIONS POUR LE CLAVIER ---
    def _keyboard_closed(self):
        self._keyboard.unbind(on_key_down=self._on_key_down)
        self._keyboard.unbind(on_key_up=self._on_key_up)
        self._keyboard = None

    def _on_key_down(self, keyboard, keycode, text, modifiers):
        key_name = keycode[1]
        command = f"KEYPRESS;{key_name}"
        send_command(command)
        return True

    def _on_key_up(self, keyboard, keycode):
        key_name = keycode[1]
        command = f"KEYRELEASE;{key_name}"
        send_command(command)
        return True
    # -----------------------------------------

    def on_start(self):
        # ... (fonction inchangée)
        host = '127.0.0.1'
        port = 9999
        connect_thread = threading.Thread(target=self.connect_and_receive, args=(host, port))
        connect_thread.daemon = True
        connect_thread.start()

    def on_stop(self):
        global is_running
        is_running = False

    def connect_and_receive(self, host, port):
        # ... (fonction inchangée)
        global client_socket
        data = b""
        header_size = struct.calcsize("!L")
        while is_running:
            is_connected = False
            while not is_connected and is_running:
                try:
                    print(f"[*] Tentative de connexion...")
                    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    client_socket.settimeout(3)
                    client_socket.connect((host, port))
                    client_socket.settimeout(None)
                    is_connected = True
                    print(f"[*] Connecté !")
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
                    while len(data) < header_size:
                        packet = client_socket.recv(4 * 1024)
                        if not packet: raise ConnectionResetError()
                        data += packet
                    packed_msg_size = data[:header_size]
                    data = data[header_size:]
                    msg_size = struct.unpack("!L", packed_msg_size)[0]
                    while len(data) < msg_size:
                        data += client_socket.recv(4 * 1024)
                    payload = data[:msg_size]
                    data = data[msg_size:]
                    res_header_size = struct.calcsize("!HH")
                    width, height = struct.unpack("!HH", payload[:res_header_size])
                    self.layout.server_resolution = (width, height)
                    jpeg_data = payload[res_header_size:]
                    Clock.schedule_once(lambda dt, frame=jpeg_data: self.layout.update_image(frame))
                except (ConnectionResetError, BrokenPipeError):
                    print("[!] Connexion perdue.")
                    is_connected = False
                    if client_socket: client_socket.close()
                    Clock.schedule_once(lambda dt: setattr(self.layout.screen_image, 'texture', None))
                    break
                except Exception:
                    is_connected = False
                    if client_socket: client_socket.close()
                    break
        if client_socket: client_socket.close()

if __name__ == "__main__":
    RemoteViewerApp().run()
