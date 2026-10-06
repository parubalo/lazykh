import argparse
import os.path
import os
import subprocess
import shutil


def hasNvenc():
    if shutil.which("nvidia-smi") is None:
        return False
    encoders = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True)
    return encoders.returncode == 0 and "h264_nvenc" in encoders.stdout

def emptyFolder(folder):
    for filename in os.listdir(folder):
        file_path = os.path.join(folder, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print('Failed to delete %s. Reason: %s' % (file_path, e))
    try:
        os.rmdir(folder)
    except Exception as e:
        print('Failed to delete %s. Reason: %s' % (folder, e))


parser = argparse.ArgumentParser(description='blah')
parser.add_argument('--input_file', type=str,  help='the script')
parser.add_argument('--keep_frames', type=str,  help='do you want to keep the thousands of frame still images, or delete them?')
parser.add_argument('--video_encoder', choices=['auto', 'cpu', 'gpu'], default='auto', help='Use the available NVIDIA encoder when possible.')
args = parser.parse_args()
INPUT_FILE = args.input_file
KEEP_FRAMES = args.keep_frames

useNvenc = args.video_encoder == 'gpu' or (args.video_encoder == 'auto' and hasNvenc())
if useNvenc and not hasNvenc():
    raise RuntimeError("The NVIDIA FFmpeg encoder is unavailable. Use --video_encoder cpu or auto.")
videoArgs = ["-c:v", "h264_nvenc", "-preset", "p4"] if useNvenc else ["-c:v", "libx264", "-preset", "veryfast"]

command = ["ffmpeg", "-y", "-framerate", "30", "-start_number", "0",
    "-i", INPUT_FILE+"_frames/f%06d.png", "-i", INPUT_FILE+".wav",
] + videoArgs + ["-b:v", "4M", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-shortest", INPUT_FILE+"_final.mp4",
]
print("Encoding with "+("NVIDIA NVENC" if useNvenc else "libx264")+".")
subprocess.run(command, check=True)

if KEEP_FRAMES == "F":
    emptyFolder(INPUT_FILE+"_frames")
