"""외부 이미지 없이 색상·기하 패턴을 계산하여 공개 시험 후보를 만든다."""
from pathlib import Path
import sys,json,hashlib,datetime
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root/'생성전용환경'))
from PIL import Image,ImageDraw
import PIL,pillow_heif
assert Path(PIL.__file__).resolve().is_relative_to(root/'생성전용환경')
assert Path(pillow_heif.__file__).resolve().is_relative_to(root/'생성전용환경')
pillow_heif.register_heif_opener()
output=root/'자체시험자료';output.mkdir(exist_ok=True)
png=output/'자체색상패턴.png';heic=output/'sample.heic'
assert not png.exists() and not heic.exists()
width,height=48,36
image=Image.new('RGB',(width,height))
for y in range(height):
    for x in range(width):
        image.putpixel((x,y),(x*255//(width-1),y*255//(height-1),32 if (x//6+y//6)%2 else 224))
draw=ImageDraw.Draw(image)
draw.rectangle((2,2,11,11),fill=(255,0,0))
draw.ellipse((28,5,43,20),fill=(0,255,0))
colors=((0,0,0),(255,255,255),(255,0,0),(0,255,0),(0,0,255),(0,255,255),(255,0,255),(255,255,0))
for index,color in enumerate(colors):draw.rectangle((index*6,28,index*6+5,35),fill=color)
image.save(png,format='PNG')
parameters=dict(quality=90,chroma='420',color_primaries=1,transfer_characteristics=13,matrix_coefficients=6,full_range_flag=1)
image.save(heic,format='HEIF',**parameters)
files=[{'filename':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in (png,heic)]
record={'kst':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(),'creator':'PUVKID','external_pixel_sources':[],'procedure':'48×36 RGB 수평·수직 그라데이션, 6픽셀 체크, 빨간 사각형, 초록 타원, 검정·흰색·기본색 띠를 직접 계산','width':width,'height':height,'mode':'RGB','bit_depth':8,'alpha':False,'frames':1,'icc_profile':None,'save_parameters':parameters,'pillow_version':PIL.__version__,'pillow_heif_version':pillow_heif.__version__,'libheif_and_encoder':pillow_heif.libheif_info(),'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'files':files}
(root/'생성조건과출처.json').write_bytes(json.dumps(record,ensure_ascii=False,indent=2).encode('utf-8'))
print(json.dumps(record,ensure_ascii=False))
