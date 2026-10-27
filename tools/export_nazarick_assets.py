"""Export generated assets. Originals stay in Codex generated_images untouched."""
from pathlib import Path
from PIL import Image, PngImagePlugin

ROOT=Path(__file__).resolve().parents[1]/'webapp/assets/nazarick'

def main():
    for path in ROOT.glob('*.png'):
        im=Image.open(path).convert('RGBA')
        if im.info.get('nazarick_exported')=='1':continue
        if path.stem.startswith('bg_'):
            im.convert('RGB').save(path.with_suffix('.webp'),quality=88,method=6)
            continue
        if path.stem in ('shalltear2','albedo1','lich'):
            # Only alpha is changed: keep every RGB pixel in the illustration.
            alpha=im.getchannel('A').point(lambda a:0 if a<180 else round((a-180)*255/75))
            im.putalpha(alpha)
        im.thumbnail((1024,1024),Image.Resampling.LANCZOS)
        meta=PngImagePlugin.PngInfo();meta.add_text('nazarick_exported','1')
        im.save(path,optimize=True,pnginfo=meta)

if __name__=='__main__':main()
