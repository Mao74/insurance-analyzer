from xhtml2pdf import pisa
from io import BytesIO

def test_pdf():
    html = "<html><body><h1>Test PDF</h1><p>It works!</p></body></html>"
    buffer = BytesIO()
    try:
        pisa_status = pisa.CreatePDF(html, dest=buffer)
        if pisa_status.err:
            print("Error: pisa_status.err is True")
        else:
            print("Success: PDF generated")
            with open("test_output.pdf", "wb") as f:
                f.write(buffer.getvalue())
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    test_pdf()
