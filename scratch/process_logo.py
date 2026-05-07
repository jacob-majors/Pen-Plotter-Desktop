from PIL import Image, ImageDraw, ImageOps

def process_logo(input_path, output_path):
    img = Image.open(input_path).convert("RGBA")
    
    # Simple crop based on visual observation of the provided image
    # The image is roughly 1000x600? Let's check size
    width, height = img.size
    
    # We want to crop to the central rounded square.
    # In the provided image, the square is roughly centered vertically and has some padding.
    # A more robust way is to find the bounding box of non-checkerboard pixels, 
    # but the checkerboard is "pixels" too. 
    # Let's try to detect the white/light-gray card area.
    
    # For now, I'll use a hardcoded crop that "zooms in" on the card based on the preview.
    # The card is roughly from y=50 to y=550 and centered horizontally.
    # Actually, let's try to find the actual content.
    
    # Assuming the card is roughly a square centered.
    size = min(width, height)
    left = (width - size) / 2
    top = (height - size) / 2
    right = (width + size) / 2
    bottom = (height + size) / 2
    
    # Zoom in a bit more to remove the outer edge
    padding = size * 0.1
    img_cropped = img.crop((left + padding, top + padding, right - padding, bottom - padding))
    
    # Apply rounded corners
    size_cropped = img_cropped.size
    mask = Image.new('L', size_cropped, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0) + size_cropped, radius=size_cropped[0]*0.15, fill=255)
    
    output = ImageOps.fit(img_cropped, size_cropped, centering=(0.5, 0.5))
    output.putalpha(mask)
    
    output.save(output_path)

if __name__ == "__main__":
    process_logo("src/assets/logo.png", "src/assets/logo.png")
