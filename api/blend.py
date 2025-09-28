import os
import numpy as np
from PIL import Image

# Folder containing your images
IMAGE_FOLDER = "images"

# Output file
OUTPUT_FILE = "blended.png"

def average_images(image_folder, output_file):
    images = []
    
    for filename in os.listdir(image_folder):
        if filename.lower().endswith((".png", ".jpg", ".jpeg")):
            img_path = os.path.join(image_folder, filename)
            img = Image.open(img_path).convert("RGBA")
            images.append(img)

    if not images:
        print("No images found.")
        return

    # Resize everything to the same size (use the first image’s size as reference)
    width, height = images[0].size
    images = [img.resize((width, height)) for img in images]

    # Convert to numpy arrays
    np_images = np.array([np.array(img, dtype=np.float32) for img in images])

    # Compute average
    avg_array = np.mean(np_images, axis=0).astype(np.uint8)

    # Save blended image
    blended = Image.fromarray(avg_array)
    blended.save(output_file)
    print(f"Blended image saved as {output_file}")


if __name__ == "__main__":
    average_images(IMAGE_FOLDER, OUTPUT_FILE)
