from ultralytics import YOLO

# Load the NEW optimized model folder
# (It will likely be named 'yolo26n-seg_openvino_model' still, but with new files)
fast_model = YOLO("models/yolo26n-seg_int8_openvino_model/")

# Run the process silently
results = fast_model.predict(
    source="/home/shiro/Desktop/a.mp4",
    save=True,
    imgsz=320,      # Match the export size for maximum speed
    device="cpu",
    stream=True,
    show=False
)

for _ in results:
    pass

print("The ritual is complete. The shadows move faster now.")
