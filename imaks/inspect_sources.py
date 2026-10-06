from pathlib import Path
from zipfile import ZipFile
from pypdf import PdfReader
import pypdfium2 as pdfium
from PIL import Image, ImageDraw
import io, json

root = Path(__file__).resolve().parent
out = root / 'pipeline_outputs' / 'sources'
out.mkdir(parents=True, exist_ok=True)
pages = []
thumbs = []
with ZipFile(root/'iMAKS_dataset.zip') as z:
    for name in sorted(z.namelist()):
        if not name.endswith('.pdf'):
            continue
        data = z.read(name)
        (out/Path(name).name).write_bytes(data)
        reader = PdfReader(io.BytesIO(data))
        renderer = pdfium.PdfDocument(data)
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            pages.append(dict(document=name, page=i+1, text=text))
            (out/f'{Path(name).stem}_p{i+1}.txt').write_text(text, encoding='utf-8')
            img = renderer[i].render(scale=1.4).to_pil().convert('RGB')
            img.save(out/f'{Path(name).stem}_p{i+1}.png')
            img.thumbnail((420,590))
            tile = Image.new('RGB',(440,620),'white')
            tile.paste(img,(10,25))
            ImageDraw.Draw(tile).text((10,5),f'{Path(name).stem} p{i+1}',fill='black')
            thumbs.append(tile)
        renderer.close()
(out/'pages.json').write_text(json.dumps(pages,ensure_ascii=False,indent=2),encoding='utf-8')
sheet = Image.new('RGB',(440*3,620*((len(thumbs)+2)//3)), '#dddddd')
for j, img in enumerate(thumbs): sheet.paste(img,((j%3)*440,(j//3)*620))
sheet.save(out/'contact_sheet.png')
print(f'{len(pages)} pages extracted and rendered')
