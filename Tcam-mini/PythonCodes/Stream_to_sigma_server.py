import cv2
import base64
import time
import json
import requests
import websocket
from threading import Thread
from PIL import Image as im
import numpy as np
from tcam import TCam
from ironblack import ironblack_palette 
from rainbow import rainbow_palette 
import cv2
import time


# IP = '127.0.0.1'
IP = '50.19.252.112'
SERIAL_NUMBER = "1010"
WS_URL = f"ws://{IP}:8390/mlai/streaming/ws/stream_thermal"
IS_STARTED_URL = f"http://{IP}:8390/mlai/streaming/is_started/{SERIAL_NUMBER}"
CAPTURE_DEVICE = 0  # Use webcam (0) or change to IP camera URL if needed
IP_Tcam = "172.17.16.59" #insert IP of Tcam here


def is_streaming():
   """Check if streaming is active for the given camera via HTTP."""
   try:
       res = requests.get(IS_STARTED_URL)
       return res.json().get('started', False)
   except Exception as e:
       print(f"Error checking streaming status: {e}")
       return False


def on_message(ws, message):
   """Handle incoming messages from the server."""
   print(f"Received message from server: {message}")


def on_error(ws, error):
   """Handle errors during WebSocket communication."""
   print(f"WebSocket error: {error}")


def on_close(ws, close_status_code, close_msg):
   """Handle WebSocket closure."""
   rsp = camera.stop_stream()
   print("WebSocket connection closed")

camera = TCam()
res = camera.connect(IP_Tcam)
print(f"success with the response : {res}")

def convert_image(mv):
    # print("Figuring out image min/max for mapping to palette")
    imgmin = 65535
    imgmax = 0

    for i in mv.tolist():
        if i < imgmin:
            imgmin = i
        if i > imgmax:
            imgmax = i

    delta = imgmax - imgmin
    transformed = []
    for i in mv:
        val = int((i - imgmin) * 255 / delta)

        if val > 255:
            transformed.append(rainbow_palette[255])
        else:
            transformed.append(rainbow_palette[val])

    a = np.zeros((120, 160, 3), np.uint8)
    for r in range(0, 120):
        for c in range(0, 160):
            a[r, c] = transformed[(r * 160) + c]
    print(type(a))
    # img = cv2.resize(a,(240,240))
    img = cv2.cvtColor(img,cv2.COLOR_BGR2RGB)
    return img


def on_open(ws):
   """Handle actions upon establishing WebSocket connection."""
   print("WebSocket connection established")


   def send_frames():
       rsp = camera.start_stream(delay_msec = 200)
       while ws.keep_running:
           
           if camera.frameQueue.empty():
                continue
           
           img = camera.get_frame()
           dimg = base64.b64decode(img["radiometric"])
           mv = memoryview(dimg).cast("H")
           frame = convert_image(mv)
           _, buffer = cv2.imencode('.jpg', frame)
           image_base64 = base64.b64encode(buffer).decode('utf-8')


           payload = json.dumps({"serialNumber": SERIAL_NUMBER, "image": image_base64})
           try:
               ws.send(payload)
           except Exception as e:
               print(f"Error sending frame: {e}")
               break


        #    time.sleep(1/5)
       rsp = camera.stop_stream()




   Thread(target=send_frames, daemon=True).start()


if __name__ == "__main__":
   websocket.enableTrace(False)
   ws_app = websocket.WebSocketApp(
       WS_URL,
       on_open=on_open,
       on_message=on_message,
       on_error=on_error,
       on_close=on_close
   )


   while True:
       if is_streaming():
           ws_app.run_forever(reconnect=5)
           print("WebSocket connection interrupted. Reconnecting in 3 seconds...")
           time.sleep(3)
       else:
           print("Streaming not started. Waiting for UI to start the stream...")
           time.sleep(3)