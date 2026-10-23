"""
AgriVision — entry point.

    python run.py            → starts the development server on port 5000
    flask --app run run      → same thing through the Flask CLI
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    print("\n  AgriVision is starting …")
    print("  Open  http://127.0.0.1:5000  in your browser")
    print("  Press CTRL+C to stop\n")
    app.run(host="127.0.0.1", port=5000, debug=True)
