def generate_handwriting_gcode(text, start_x, start_y, scale=1.0):
    gcode = []
    gcode.append("G90") # Absolute
    gcode.append(f"G0 X{start_x} Y{start_y} Z5") # Move to start
    gcode.append("G0 Z-2") # Pen down
    
    # Simulate drawing text
    # In full implementation, map `text` characters to Hershey font vectors
    
    gcode.append(f"G1 X{start_x+10} Y{start_y+10} F1500")
    gcode.append("G0 Z5") # Pen up
    return gcode
