import google.generativeai as genai
import json

def solve_with_gemini(api_key, image, prompt):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-pro-latest')
    
    # This is a mockup of parsing a worksheet and extracting bounding boxes
    return {
        "answers": [
            {"text": "Photosynthesis", "x": 100, "y": 200},
            {"text": "Mitochondria", "x": 100, "y": 300}
        ]
    }
