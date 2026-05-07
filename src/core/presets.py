import math

def generate_spirograph(center_x=110, center_y=110, R=40, r=15, a=20, points=1000):
    paths = []
    current_path = []
    for i in range(points):
        t = i * 0.1
        x = center_x + (R - r) * math.cos(t) + a * math.cos((R - r) * t / r)
        y = center_y + (R - r) * math.sin(t) - a * math.sin((R - r) * t / r)
        current_path.append((x, y))
    paths.append(current_path)
    return paths

def generate_fractal_star(center_x=110, center_y=110, radius=80, points=8, depth=3):
    paths = []
    
    def draw_star(cx, cy, r, d):
        if d == 0:
            return
        
        path = []
        for i in range(points * 2 + 1):
            angle = i * math.pi / points
            rad = r if i % 2 == 0 else r * 0.4
            x = cx + rad * math.cos(angle)
            y = cy + rad * math.sin(angle)
            path.append((x, y))
        paths.append(path)
        
        for i in range(points):
            angle = i * 2 * math.pi / points
            next_cx = cx + r * math.cos(angle)
            next_cy = cy + r * math.sin(angle)
            draw_star(next_cx, next_cy, r * 0.3, d - 1)

    draw_star(center_x, center_y, radius, depth)
    return paths

def generate_shaded_sphere(center_x=110, center_y=110, radius=60, use_pencil=True):
    paths = []
    
    # Draw outline
    outline = []
    for i in range(101):
        angle = i * 2 * math.pi / 100
        outline.append((center_x + radius * math.cos(angle), center_y + radius * math.sin(angle)))
    paths.append(outline)
    
    if not use_pencil:
        return paths
        
    light_x = center_x - radius * 0.4
    light_y = center_y - radius * 0.4

    # Generate cross-hatching
    # Angle in degrees, spacing density, threshold darkness required to draw
    layers = [
        (45, 3.0, 0.3),   # Base shading
        (-45, 2.5, 0.6),  # Cross shading for darker areas
        (0, 2.0, 0.8)     # Horizontal for darkest shadow core
    ]
    
    for angle_deg, density, light_threshold in layers:
        angle = math.radians(angle_deg)
        dx = math.cos(angle)
        dy = math.sin(angle)
        px = -dy
        py = dx
        
        offset = -radius
        while offset < radius:
            h2 = radius**2 - offset**2
            if h2 <= 0:
                offset += density
                continue
                
            h = math.sqrt(h2)
            ox = center_x + px * offset
            oy = center_y + py * offset
            
            start_x = ox - dx * h
            start_y = oy - dy * h
            end_x = ox + dx * h
            end_y = oy + dy * h
            
            mid_x = (start_x + end_x) / 2
            mid_y = (start_y + end_y) / 2
            
            dist_to_light = math.sqrt((mid_x - light_x)**2 + (mid_y - light_y)**2)
            normalized_darkness = dist_to_light / (radius * 2)
            
            if normalized_darkness > light_threshold:
                paths.append([(start_x, start_y), (end_x, end_y)])
                
            offset += density
            
    return paths

def generate_rose_curve(center_x=110, center_y=110, radius=80, n=5, d=1):
    paths = []
    path = []
    k = n / d
    points = 1000
    # For n/d to close, we need 2*pi * d if n*d is even, or pi * d if n*d is odd
    # To be safe, 2*pi*d always works
    for i in range(points + 1):
        t = (i / points) * 2 * math.pi * d
        r = radius * math.cos(k * t)
        x = center_x + r * math.cos(t)
        y = center_y + r * math.sin(t)
        path.append((x, y))
    paths.append(path)
    return paths

def generate_golden_spiral(center_x=110, center_y=110, size=150):
    paths = []
    path = []
    phi = (1 + math.sqrt(5)) / 2
    points = 500
    for i in range(points):
        t = (i / points) * 10 * math.pi
        r = (phi ** (2 * t / math.pi)) * 0.5
        if r > size: break
        x = center_x + r * math.cos(t)
        y = center_y + r * math.sin(t)
        path.append((x, y))
    paths.append(path)
    return paths

def generate_hilbert_curve(center_x=110, center_y=110, size=160, order=4):
    paths = []
    path = []
    
    def rot(n, x, y, rx, ry):
        if ry == 0:
            if rx == 1:
                x = n - 1 - x
                y = n - 1 - y
            return y, x
        return x, y

    def d2xy(n, d):
        x = y = 0
        t = d
        s = 1
        while s < n:
            rx = 1 & (t // 2)
            ry = 1 & (t ^ rx)
            x, y = rot(s, x, y, rx, ry)
            x += s * rx
            y += s * ry
            t //= 4
            s *= 2
        return x, y

    n = 2**order
    scale = size / n
    start_x = center_x - size/2
    start_y = center_y - size/2
    
    for i in range(n*n):
        hx, hy = d2xy(n, i)
        path.append((start_x + hx * scale, start_y + hy * scale))
    
    paths.append(path)
    return paths

def generate_lissajous(center_x=110, center_y=110, width=80, height=80, a=3, b=2, delta=math.pi/2):
    paths = []
    path = []
    points = 1000
    for i in range(points + 1):
        t = (i / points) * 2 * math.pi
        x = center_x + width * math.sin(a * t + delta)
        y = center_y + height * math.sin(b * t)
        path.append((x, y))
    paths.append(path)
    return paths

def generate_sierpinski(center_x=110, center_y=110, size=160, depth=5):
    paths = []
    
    def draw_triangle(p1, p2, p3, d):
        if d == 0:
            paths.append([p1, p2, p3, p1])
            return
        
        m12 = ((p1[0]+p2[0])/2, (p1[1]+p2[1])/2)
        m23 = ((p2[0]+p3[0])/2, (p2[1]+p3[1])/2)
        m31 = ((p3[0]+p1[0])/2, (p3[1]+p1[1])/2)
        
        draw_triangle(p1, m12, m31, d - 1)
        draw_triangle(m12, p2, m23, d - 1)
        draw_triangle(m31, m23, p3, d - 1)

    h = size * math.sqrt(3) / 2
    p1 = (center_x, center_y + 2/3 * h)
    p2 = (center_x - size/2, center_y - 1/3 * h)
    p3 = (center_x + size/2, center_y - 1/3 * h)
    
    draw_triangle(p1, p2, p3, depth)
    return paths

def generate_dragon_curve(center_x=110, center_y=110, length=4, depth=10):
    paths = []
    path = [(center_x, center_y)]
    
    def build_dragon(x, y, angle, d, turn):
        if d == 0:
            nx = x + length * math.cos(math.radians(angle))
            ny = y + length * math.sin(math.radians(angle))
            path.append((nx, ny))
            return nx, ny, angle
        
        nx, ny, angle = build_dragon(x, y, angle + 45 * turn, d - 1, 1)
        return build_dragon(nx, ny, angle - 90 * turn, d - 1, -1)

    build_dragon(center_x - 50, center_y, 0, depth, 1)
    paths.append(path)
    return paths

def generate_phyllotaxis(center_x=110, center_y=110, n_dots=400, spread=6):
    paths = []
    angle_offset = 137.5 # Golden angle
    for i in range(n_dots):
        angle = math.radians(i * angle_offset)
        r = spread * math.sqrt(i)
        x = center_x + r * math.cos(angle)
        y = center_y + r * math.sin(angle)
        seed_path = []
        for sa_deg in range(0, 361, 60):
            sa = math.radians(sa_deg)
            seed_path.append((x + 1.5 * math.cos(sa), y + 1.5 * math.sin(sa)))
        paths.append(seed_path)
    return paths
