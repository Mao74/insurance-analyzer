from weasyprint import HTML
import sys

def test_weasy():
    print("Testing WeasyPrint...")
    try:
        html = "<html><body><h1>Test WeasyPrint</h1><p>It works!</p></body></html>"
        pdf = HTML(string=html).write_pdf()
        with open("test_weasy.pdf", "wb") as f:
            f.write(pdf)
        print("Success: test_weasy.pdf generated")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_weasy()
