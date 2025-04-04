import os
import json
import time
import requests
from PIL import Image as im
import random
from threading import Thread
from tcam import TCam
from ironblack import ironblack_palette 
from rainbow import rainbow_palette
import cv2
import queue 
import base64
import numpy as np
import shutil

# Configuration
SERVER_URL = "https://1l81c00w-5000.inc1.devtunnels.ms/"  # Update with your server URL
OFFLINE_STORAGE_DIR = "offline_storage"
RETRY_INTERVAL = 0.5  # Seconds between retry attempts
MAX_SIMULTANEOUS_SEND = 10  # Max parallel send attempts


# Ensure offline directory exists
os.makedirs(OFFLINE_STORAGE_DIR, exist_ok=True)


def writer_thread_func(q, writer):
    """Continuously pull frames from the queue and write them to the video."""
    while True:
        if q.empty() :
            continue
        frame = q.get()
        if frame is None:  # Sentinel value to signal the end of processing
            q.task_done()
            break
        writer.write(frame)
        q.task_done()
    print("Writer thread has exited.")

def send_video_to_server(video_path):
    try:
        with open(video_path, 'rb') as video_file:
            st = time.time()
            files = {'video': (video_path, video_file, 'video/mp4')}
            response = requests.post(f'{SERVER_URL}api/upload', files=files, timeout=1000)
            et = time.time()
            response.raise_for_status()
            print(f"Video sent in {et- st} time")
            return True
    except requests.exceptions.RequestException as e:
        # Optionally, log the exception e for debugging
        print("Sent video failed : Server ERROR")
        return False



def send_to_server(json_data):
    """Attempt to send JSON data to the server."""
    try:
        st = time.time()
        json_dd = {"hello" : "hi"}
        response = requests.post(f'{SERVER_URL}api/data', json=json_data, timeout=20)
        et = time.time()
        response.raise_for_status()
        print(f"JSON sent in {et- st} time")
        return True
    except requests.exceptions.RequestException as e:
        print("Sent JSON failed : Server ERROR")
        return False

def send_trial():
    """Attempt to send JSON data to the server."""
    try:
        st = time.time()
        response = requests.get(f'{SERVER_URL}check',timeout=2)
        et = time.time()
        response.raise_for_status()
        print(f"JSON get in {et- st} time")
        return True
    except requests.exceptions.RequestException as e:
        print("Sent video failed : Server ERROR")
        return False

def save_to_offline(json_data):
    """Save JSON data to offline storage with timestamp.""" 
    timestamp = int(time.time() * 1000)
    filename = f"data_{timestamp}.json"
    filepath = os.path.join(OFFLINE_STORAGE_DIR, filename)
    try:
        with open(filepath, 'w') as f:
            json.dump(json_data, f)
    except Exception as e:
        print(f"Error saving offline data: {e}")

def handle_incoming_json(json_data):
    """Process incoming JSON data."""
    if not send_to_server(json_data):
        save_to_offline(json_data)

def handle_incoming_video(video_path,video_save_path):
    """Process incoming JSON data."""
    if not send_video_to_server(video_path):
        shutil.move(video_path, video_save_path)
        

def retry_offline_files():
    """Background thread to retry sending offline files."""
    while True:
        try:
            files = os.listdir(OFFLINE_STORAGE_DIR)
            if not files:
                time.sleep(RETRY_INTERVAL)
                continue

            # Try to send each file
            for filename in files:

                filepath = os.path.join(OFFLINE_STORAGE_DIR, filename)
                if filepath.endswith('mp4'):
                    try:
                        if send_video_to_server(filepath):
                            os.remove(filepath)
                        else:
                            print("Video Failed to send will try again")
                            break
                    except Exception as e:
                        print(f"Error processing {filename}: {e}")
                    continue

                try:
                    with open(filepath, 'r') as f:
                        json_data = json.load(f)
                    if send_to_server(json_data):
                        os.remove(filepath)
                        print(f"Successfully resent: {filename}")
                    else:
                        break  # Stop if server becomes unavailable
                except Exception as e:
                    print(f"Error processing {filename}: {e}")

            time.sleep(RETRY_INTERVAL)
        except Exception as e:
            print(f"Retry thread error: {e}")
            time.sleep(RETRY_INTERVAL)

def get_video_event():
    frame_queue = queue.Queue(maxsize=100)
    ct = time.time()
    VIDEO_FILE = f"output_{int(ct)}.mp4"
    VIDEO_FILE_NAME = f"{OFFLINE_STORAGE_DIR}/{VIDEO_FILE}"
    
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    video_out = cv2.VideoWriter(VIDEO_FILE, fourcc, 8.0, (640, 480))

    st = time.time()
    camera = TCam()
    res = camera.connect("192.168.4.1")
    print(f"success with the response : {res}")

    writer_thread = Thread(target=writer_thread_func, args=(frame_queue, video_out))
    writer_thread.start()

    rsp = camera.start_stream()
    print(rsp)
    count = 1
    json_data ={}

    while count < 120:

        if camera.frameQueue.empty():
            continue
        img = camera.get_frame()
        json_data[count] = img["radiometric"]
        dimg = base64.b64decode(img["radiometric"])
        # print(img)
        mv = memoryview(dimg).cast("H")

        print("Figuring out image min/max for mapping to palette")
        imgmin = 65535
        imgmax = 0

        for i in mv.tolist():
            if i < imgmin:
                imgmin = i
            if i > imgmax:
                imgmax = i

        delta = imgmax - imgmin
        print(f"Max val is {imgmax}, Min val is {imgmin}, Delta is {delta}")

        # now we form the 8 bit range from the min and delta.  This allows us to bracket the 16 bit data into
        # an 8 bit range, and then use the 8 bits to look up the palette data for the pixel value.
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
        # print(type(a))
        img = cv2.resize(a,(640,480))
        img = cv2.cvtColor(img,cv2.COLOR_BGR2RGB)
        
        frame_queue.put(img)

        et = time.time()
        count+=1
        print(f'FPS is : {count/(et-st)}')
        # data.save(outfile)
        
    frame_queue.put(None)
    writer_thread.join()
    rsp = camera.stop_stream()
    camera.shutdown()
    video_out.release()
    handle_incoming_json(json_data)
    handle_incoming_video(VIDEO_FILE,VIDEO_FILE_NAME)

def simulate_event_trigger():
    """Simulate receiving 160 JSONs in ~20 seconds."""
    start_time = time.time()
    count =  1   
    
    while count < 160:
        json_data = {
            "id": count,
            "timestamp": time.time(),
            "content": f"Event {count}"
        }
        
        handle_incoming_json(json_data)
        
        # Calculate dynamic sleep time to spread 160 events over 20 seconds
        elapsed = time.time() - start_time
        remaining_time = max(0, 20 - elapsed)
        remaining_events = 160 - count
        
        if remaining_events > 0 and remaining_time > 0:
            sleep_time = remaining_time / remaining_events
            # time.sleep(sleep_time * random.uniform(0.5, 1.5))
        
        count += 1

if __name__ == "__main__":
    # Start retry thread
    retry_thread = Thread(target=retry_offline_files, daemon=True)
    retry_thread.start()

    # Simulate event triggers
    # simulate_event_trigger()
    # get_video_event()

    # Keep main thread alive
    while True:
        send_trial()
        time.sleep(1)