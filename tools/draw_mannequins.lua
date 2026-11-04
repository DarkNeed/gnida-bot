-- Aseprite 1.3: pixel-native mannequin studies, not image-generator output.
-- Run: aseprite -b --script-param outdir=... --script tools/draw_mannequins.lua
local root = assert(app.params.outdir, "Pass --script-param outdir=<output directory>")
local rgba = app.pixelColor.rgba
local function color(hex)
  return rgba(tonumber(hex:sub(1,2),16),tonumber(hex:sub(3,4),16),tonumber(hex:sub(5,6),16),255)
end
local C = {}
for key,value in pairs({
  ink="202338", white="FCF7ED", porcelain="C7D1DE", porcelainDark="899BAD",
  dark="38394F", darkShade="292D40", darkLight="55566A",
  brown="9D6B4B", brownShade="68483D", brownLight="CD9A64", patch="E3BB81",
  red="DD5661", redShade="923849", redLight="F68F86",
  purple="9675CF", purpleShade="5F4C99", purpleLight="C6A5E8", pink="F29CCB",
  teal="54B5B4", tealShade="347982", tealLight="97D5CF", cyan="B5F2E7",
  gray="8E97AA", grayShade="596578", grayLight="C4CDDA",
  backdrop="202B40", panel="28364E", grid="34435C", muted="99AAC7"
}) do C[key]=color(value) end

local function inside(x,y,points)
  local hit=false
  local j=#points
  for i=1,#points do
    local a,b=points[i],points[j]
    if (a[2]>y)~=(b[2]>y) and x<(b[1]-a[1])*(y-a[2])/(b[2]-a[2])+a[1] then hit=not hit end
    j=i
  end
  return hit
end

local function painter(image,n)
  local scale=n/36
  local edge=n==128 and 2 or 1
  local function mask(test,fill,stroke)
    stroke=stroke==nil and edge or stroke
    for y=0,n-1 do for x=0,n-1 do
      if test((x+.5)/scale,(y+.5)/scale) then
        local border=stroke>0 and (
          not test((x+.5-stroke)/scale,(y+.5)/scale) or
          not test((x+.5+stroke)/scale,(y+.5)/scale) or
          not test((x+.5)/scale,(y+.5-stroke)/scale) or
          not test((x+.5)/scale,(y+.5+stroke)/scale))
        image:drawPixel(x,y,border and C.ink or fill)
      end
    end end
  end
  local function poly(points,fill,stroke)
    mask(function(x,y) return inside(x,y,points) end,fill,stroke)
  end
  local function rect(x,y,w,h,fill,stroke)
    mask(function(px,py) return px>=x and px<x+w and py>=y and py<y+h end,fill,stroke)
  end
  local function oval(cx,cy,rx,ry,fill,stroke)
    mask(function(x,y) return ((x-cx)/rx)^2+((y-cy)/ry)^2<=1 end,fill,stroke)
  end
  local function pixel(x,y,fill)
    image:drawPixel(math.floor(x*scale),math.floor(y*scale),fill)
  end
  return {poly=poly,rect=rect,oval=oval,pixel=pixel}
end

local function render(n,class,attack)
  local images={Image(n,n),Image(n,n),Image(n,n),Image(n,n)}
  local body,cloth,detail,fx=painter(images[1],n),painter(images[2],n),painter(images[3],n),painter(images[4],n)
  local hx=attack and 19.2 or 18
  local nearHand=attack and {31.5,14} or {25.2,13.4}
  local farHand=attack and {14.3,17.4} or {12.4,15.2}
  if class=="cutie" then nearHand=attack and {28.8,14} or {25.8,14.5} end
  if class=="nerd" then
    nearHand=attack and {28.5,14} or {24.8,18.5}
    farHand=attack and {13.3,20.1} or {12.7,21.5}
  end
  -- Neutral mannequin under the costume. No face or sex-specific anatomy.
  body.poly({{14,11},{21,11},{23,19},{20,23},{14,23},{12,18}},C.porcelain)
  body.poly({{14,13},{11,15},{10.5,19},{farHand[1],farHand[2]+1},{15,16}},C.porcelain)
  body.poly({{21,12},{nearHand[1]+1,nearHand[2]-1.5},{nearHand[1]+1,nearHand[2]+1.5},{22,17},{19,16}},C.white)
  local pants=class=="jock" and C.gray or class=="cutie" and C.purpleShade or C.dark
  local pantsShade=class=="jock" and C.grayShade or C.darkShade
  local legs=attack and {{14,20},{21,20},{28,30.5},{24,32},{18.5,25},{12,31},{8.5,30.5}}
                         or {{13,20},{21,20},{25,31.5},{20,32},{17.5,25},{14,32},{9,31}}
  cloth.poly(legs,pants)
  cloth.poly(attack and {{14,22},{17.8,24},{12,31},{9.5,30.5}} or {{13.5,22},{17,25},{13.5,31},{10,30.5}},pantsShade,0)
  cloth.poly(attack and {{21,23},{26.5,30.5},{24.5,31},{20,25}} or {{21,23},{23.7,30.8},{21,31},{19,25}},pantsShade,0)
  local shoes=class=="ragamuffin" and C.brown or class=="jock" and C.red or C.darkShade
  local leftX=attack and 8 or 8.7
  local rightX=attack and 24 or 20
  cloth.poly({{leftX+1,30},{leftX+5,30},{leftX+6.5,33.5},{leftX,33.5}},shoes)
  cloth.poly({{rightX,30},{rightX+4,30},{rightX+6.5,32},{rightX+6.5,33.5},{rightX-.5,33.5}},shoes)

  if class=="ragamuffin" then
    cloth.poly({{13.5,11},{21.5,11.5},{23,18},{22.5,24},{24,27},{20,26},{18.5,28},{16,26},{13,28},{9,26},{11,20},{11.5,14}},C.brown)
    cloth.poly({{13.5,12},{16,13},{15,22},{12,26},{10.5,25},{12,20}},C.brownShade,0)
    cloth.poly({{20,13},{22,15},{22,23},{20,25},{19,21}},C.brownLight,0)
    cloth.poly({{13,12},{11,14},{10.5,18},{farHand[1],farHand[2]+2},{15,15}},C.brown)
    cloth.poly({{21,12},{nearHand[1]-1.5,nearHand[2]-2},{nearHand[1]-1,nearHand[2]+2},{20,16}},C.brown)
    cloth.poly(attack and {{15,10},{12,10.5},{6,8},{4.5,10},{10,12},{14,12.5}}
                      or {{15,10},{12,10.5},{9,13.5},{8,17},{10,17.5},{12.5,13},{16,12}},C.redShade)
    cloth.poly({{15,10.5},{21,10.5},{22,12},{18,13.5},{14,12.5}},C.red)
    detail.rect(12.5,22,3.2,3,C.patch,0)
    detail.rect(20,16.5,1.8,2.7,C.brownShade,0)
    detail.rect(leftX+.7,32,4.9,.6,C.brownLight,0)
    detail.rect(rightX+.6,32,5,.6,C.brownLight,0)
  elseif class=="cutie" then
    -- Short cape, trousers and collar bow; all gender-neutral.
    cloth.poly(attack and {{14,11},{21,11},{24,16},{21.5,20},{17,21.5},{10,23.5},{6,22},{10,16}}
                      or {{14,11},{21,11},{25,16},{23,21},{18,22},{13,20},{8,21},{10,16}},C.purple)
    cloth.poly({{12,13},{14,15},{13,19},{9,20},{10.5,17}},C.purpleShade,0)
    cloth.poly({{20,12},{23,15},{22,19},{20,20},{18.5,17}},C.purpleLight,0)
    cloth.poly({{13,13},{11,14},{farHand[1]-1,farHand[2]+2},{farHand[1]+2,farHand[2]+2},{16,15}},C.purple)
    cloth.poly({{21,12},{nearHand[1]-1,nearHand[2]-2},{nearHand[1],nearHand[2]+1.7},{20,16}},C.purple)
    detail.poly({{16,12},{14.5,11.7},{14.5,14},{17,13.6},{18,14},{20,13.5},{20,11.7},{18,12.2}},C.pink,0)
    detail.rect(leftX+.5,32.5,5.2,.6,C.purpleLight,0)
    detail.rect(rightX+.1,32.5,6,.6,C.purpleLight,0)
    if attack then
      fx.poly({{31,10.8},{32.2,9.8},{33.4,10.7},{34,9.9},{35,10.8},{35,12.1},{32.9,14.2},{30.8,12}},C.pink,0)
      fx.rect(29.7,9,.45,.45,C.purpleLight,0)
    end
  elseif class=="jock" then
    cloth.poly({{13.5,11.5},{16,12.5},{19,12.5},{21.5,11.5},{23,20.5},{13,20.5}},C.dark)
    cloth.poly({{14,14},{16,15},{16,19.5},{13.5,19.5}},C.darkLight,0)
    detail.poly({{20,12.3},{21.2,12},{21,19.7},{20.2,19.7}},C.red,0)
    detail.poly(attack and {{23,25},{25,29.5},{24.5,30},{22.4,25}} or {{21.5,24},{23,29.5},{22.5,30},{21,24}},C.grayLight,0)
    detail.rect(leftX+.2,32.5,5.8,.55,C.white,0)
    detail.rect(rightX,32.5,6.2,.55,C.white,0)
  else
    cloth.poly({{13,11.5},{21,11.5},{23.5,18},{22,22},{13,22},{11,17}},C.teal)
    cloth.poly({{13,12.5},{16,14},{15,21},{13,21},{11.7,17}},C.tealShade,0)
    cloth.poly({{19,13},{21,13},{22,17},{20.5,19.5},{19.5,17}},C.tealLight,0)
    cloth.poly({{13,12},{10.5,14},{farHand[1]-2,farHand[2]+1},{farHand[1]+1,farHand[2]+2},{15,16}},C.teal)
    cloth.poly({{21,12},{nearHand[1]-1,nearHand[2]-2.1},{nearHand[1]-.8,nearHand[2]+1.7},{20,16}},C.teal)
    detail.poly({{14,11.4},{15,13},{18,14},{21.5,12},{21,10.8}},C.tealShade,0)
    detail.rect(16,19,4.5,1.2,C.tealShade,0)
    detail.rect(leftX+.3,32.5,5.6,.55,C.tealLight,0)
    detail.rect(rightX,32.5,6,.55,C.tealLight,0)
    if attack then
      fx.rect(32,12,1.3,1.3,C.cyan,0)
      fx.rect(34,10.3,.7,.7,C.tealLight,0)
      fx.rect(32.2,15.1,.8,.8,C.cyan,0)
    end
  end

  -- Porcelain head above collars: deliberately no facial marks at any size.
  detail.rect(hx-1.5,10,3,2.5,C.porcelain,0)
  detail.oval(hx,6.8,3.65,4.75,C.white)
  detail.poly({{hx-3.2,4.8},{hx-2.1,3.3},{hx-2.3,8.4},{hx-1.3,10.4},{hx-2.2,10},{hx-3.2,8.5}},C.porcelain,0)
  detail.oval(farHand[1],farHand[2],1.6,1.8,C.white)
  detail.oval(nearHand[1],nearHand[2],1.65,1.8,C.white)

  if class=="jock" then
    detail.oval(farHand[1],farHand[2],2.8,3,C.red)
    detail.oval(nearHand[1],nearHand[2],2.8,3,C.red)
    detail.poly({{nearHand[1]-1.4,nearHand[2]-1.7},{nearHand[1]+.4,nearHand[2]-2},{nearHand[1]+1.2,nearHand[2]-1.1},{nearHand[1]-1.4,nearHand[2]-.8}},C.redLight,0)
    detail.rect(nearHand[1]-2.7,nearHand[2]+1,1.1,1.2,C.porcelain,0)
    detail.rect(farHand[1]-1,farHand[2]+1.5,2,.6,C.porcelain,0)
  elseif class=="nerd" then
    detail.poly({{hx-4,7.5},{hx-4.5,4.5},{hx-3,1.8},{hx,1.1},{hx+3.3,2.6},{hx+3.8,4},{hx+2.9,3.3},{hx,2.1},{hx-2.6,2.7},{hx-3.3,5},{hx-3.1,7.5}},C.darkShade,0)
    detail.rect(hx-4.6,5.2,2.5,3.2,C.darkShade,0)
    detail.rect(hx-4.2,5.8,1.2,2,C.tealLight,0)
    local can=attack and farHand or nearHand
    detail.rect(can[1]-.8,can[2]-2.7,2.6,4,C.darkShade)
    detail.rect(can[1]-.35,can[2]-2.1,1.7,2.3,C.teal,0)
    detail.rect(can[1]-.5,can[2]-2.8,2,.45,C.porcelain,0)
    detail.rect(can[1]-.1,can[2]+.4,1.2,.65,C.white,0)
  end

  -- Resolution-specific detailing; not scaled copies of the 36px bitmap.
  if n>=64 then
    if class=="ragamuffin" then
      detail.rect(12.5,21.5,3.2,.35,C.brownShade,0)
      for x=12.6,15.5,.75 do detail.pixel(x,22,C.brownShade); detail.pixel(x,24.7,C.brownShade) end
      detail.poly({{17,14},{17.6,14},{16.6,24.7},{16,25.2}},C.brownShade,0)
      detail.rect(20.1,16.5,1.5,.35,C.brownLight,0)
    elseif class=="cutie" then
      detail.poly({{10.5,19.5},{12,18.8},{14.2,20},{14,20.5},{12,19.6}},C.purpleLight,0)
      detail.rect(16.7,12.4,.7,.7,C.white,0)
      detail.poly({{20,17.8},{20.5,18},{21.8,20},{21.3,20.3}},C.purpleShade,0)
    elseif class=="jock" then
      detail.rect(16.4,19.6,3.5,.35,C.grayShade,0)
      detail.rect(leftX+2,31,1.4,.4,C.redLight,0)
      detail.rect(rightX+2,31,1.5,.4,C.redLight,0)
    else
      detail.rect(17.7,14.1,.4,6.9,C.tealShade,0)
      detail.rect(14.8,14.2,.4,2,C.white,0)
      detail.rect(19,14.2,.4,2,C.white,0)
      detail.rect(hx-3.9,6.1,.35,1.3,C.cyan,0)
    end
  end
  if n==128 then
    local stitch=class=="ragamuffin" and C.brownLight or class=="cutie" and C.purpleLight or class=="jock" and C.grayLight or C.tealLight
    for x=14,20,.55 do detail.pixel(x,20.7,stitch) end
    for offset=0,2,.65 do
      detail.rect(leftX+2,30.9+offset*.4,1.4,.16,C.porcelain,0)
      detail.rect(rightX+1.6,30.9+offset*.4,1.6,.16,C.porcelain,0)
    end
    if class=="nerd" then
      local can=attack and farHand or nearHand
      detail.poly({{can[1]+.5,can[2]-1.9},{can[1]-.1,can[2]-.8},{can[1]+.4,can[2]-.8},{can[1],can[2]-.1},{can[1]+1,can[2]-1.2},{can[1]+.5,can[2]-1.2}},C.cyan,0)
    end
  end
  local composite=Image(n,n)
  for _,image in ipairs(images) do composite:drawImage(image) end
  return images,composite
end

local classes={"ragamuffin","cutie","jock","nerd"}
local titles={"RAGAMUFFIN","CUTIE","JOCK","NERD"}
local sizes={36,64,128}
local all={}
local names={"01 Mannequin","02 Costume","03 Details","04 Effects"}
local function path(name) return root.."/"..name end
local function save_png(image,name) image:saveAs(path(name)) end
for _,n in ipairs(sizes) do
  all[n]={}
  local atlas=Image(n*4,n*2)
  for index,class in ipairs(classes) do
    local sprite=Sprite(n,n,ColorMode.RGB)
    local layers={sprite.layers[1],sprite:newLayer(),sprite:newLayer(),sprite:newLayer()}
    for k,layer in ipairs(layers) do layer.name=names[k] end
    sprite:newEmptyFrame(2)
    all[n][index]={}
    for frame=1,2 do
      local images,composite=render(n,class,frame==2)
      for k,layer in ipairs(layers) do sprite:newCel(layer,frame,images[k],Point(0,0)) end
      sprite.frames[frame].duration=frame==1 and .6 or .2
      all[n][index][frame]=composite
      save_png(composite,n.."/"..class..(frame==1 and "-idle.png" or "-attack.png"))
      atlas:drawImage(composite,Point((index-1)*n,(frame-1)*n))
    end
    sprite:newTag(1,1).name="idle"
    sprite:newTag(2,2).name="attack"
    sprite.gridBounds=Rectangle(0,0,1,1)
    sprite:saveAs(path(n.."/"..class..".aseprite"))
    local sheet=Image(n*2,n)
    sheet:drawImage(all[n][index][1],Point(0,0))
    sheet:drawImage(all[n][index][2],Point(n,0))
    save_png(sheet,n.."/"..class.."-sheet.png")
    sprite:close()
  end
  save_png(atlas,n.."/atlas.png")
end

-- Presentation images: exact integer nearest-neighbor enlargement only.
local glyph={
 A={"01110","10001","10001","11111","10001","10001","10001"},
 C={"01111","10000","10000","10000","10000","10000","01111"},
 D={"11110","10001","10001","10001","10001","10001","11110"},
 E={"11111","10000","10000","11110","10000","10000","11111"},
 F={"11111","10000","10000","11110","10000","10000","10000"},
 G={"01111","10000","10000","10111","10001","10001","01111"},
 I={"11111","00100","00100","00100","00100","00100","11111"},
 J={"00111","00010","00010","00010","00010","10010","01100"},
 K={"10001","10010","10100","11000","10100","10010","10001"},
 L={"10000","10000","10000","10000","10000","10000","11111"},
 M={"10001","11011","10101","10101","10001","10001","10001"},
 N={"10001","11001","10101","10011","10001","10001","10001"},
 O={"01110","10001","10001","10001","10001","10001","01110"},
 P={"11110","10001","10001","11110","10000","10000","10000"},
 Q={"01110","10001","10001","10001","10101","10010","01101"},
 R={"11110","10001","10001","11110","10100","10010","10001"},
 S={"01111","10000","10000","01110","00001","00001","11110"},
 T={"11111","00100","00100","00100","00100","00100","00100"},
 U={"10001","10001","10001","10001","10001","10001","01110"},
 V={"10001","10001","10001","10001","10001","01010","00100"},
 X={"10001","10001","01010","00100","01010","10001","10001"},
 ["0"]={"01110","10001","10011","10101","11001","10001","01110"},
 ["1"]={"00100","01100","00100","00100","00100","00100","01110"},
 ["2"]={"01110","10001","00001","00010","00100","01000","11111"},
 ["3"]={"11110","00001","00001","01110","00001","00001","11110"},
 ["4"]={"00010","00110","01010","10010","11111","00010","00010"},
 ["6"]={"01110","10000","10000","11110","10001","10001","01110"},
 ["8"]={"01110","10001","10001","01110","10001","10001","01110"},
 [" "]={"00000","00000","00000","00000","00000","00000","00000"}
}
local function text(im,value,x,y,zoom,fill)
  for i=1,#value do
    local letter=assert(glyph[value:sub(i,i)],"Missing glyph: "..value:sub(i,i))
    for row=1,7 do for col=1,5 do if letter[row]:sub(col,col)=="1" then
      for dy=0,zoom-1 do for dx=0,zoom-1 do
        im:drawPixel(x+(i-1)*6*zoom+(col-1)*zoom+dx,y+(row-1)*zoom+dy,fill)
      end end
    end end end
  end
end
local function background(im) im:clear(C.backdrop) end
local function enlargement(dst,src,x,y,zoom,grid)
  for sy=0,src.height-1 do for sx=0,src.width-1 do
    local col=src:getPixel(sx,sy)
    local opaque=app.pixelColor.rgbaA(col)>0
    for dy=0,zoom-1 do for dx=0,zoom-1 do
      local base=((math.floor(sx/4)+math.floor(sy/4))%2==0) and C.panel or C.backdrop
      dst:drawPixel(x+sx*zoom+dx,y+sy*zoom+dy,opaque and col or base)
    end end
    if grid and not opaque then dst:drawPixel(x+sx*zoom,y+sy*zoom,C.grid) end
  end end
end
for _,n in ipairs(sizes) do
  local zoom=n==36 and 6 or n==64 and 4 or 2
  local cell=n*zoom
  local width=4*(cell+20)+20
  local preview=Image(width,2*(cell+28)+66)
  background(preview)
  text(preview,n.."X"..n,20,14,2,C.white)
  for index=1,4 do
    local x=20+(index-1)*(cell+20)
    text(preview,titles[index],x,40,2,C.tealLight)
    for frame=1,2 do
      local y=62+(frame-1)*(cell+28)
      enlargement(preview,all[n][index][frame],x,y,zoom,false)
      text(preview,frame==1 and "IDLE" or "ATTACK",x,y+cell+6,1,C.muted)
    end
  end
  save_png(preview,n.."/preview.png")
end
local overview=Image(1344,626)
background(overview)
text(overview,"MANNEQUINS",20,14,2,C.white)
for index=1,4 do text(overview,titles[index],100+(index-1)*312,44,2,C.tealLight) end
for row,n in ipairs(sizes) do
  local zoom=n==36 and 4 or n==64 and 2 or 1
  local y=76+(row-1)*182
  text(overview,n.."X"..n,12,y+62,1,C.muted)
  for index=1,4 do for frame=1,2 do
    local x=100+(index-1)*312+(frame-1)*152
    enlargement(overview,all[n][index][frame],x,y,zoom,false)
    text(overview,frame==1 and "IDLE" or "ATTACK",x,y+150,1,C.muted)
  end end
end
save_png(overview,"overview.png")

-- Verify the actual deliverables, including binary alpha and native canvas sizes.
for _,n in ipairs(sizes) do for _,class in ipairs(classes) do
  local sprite=app.open(path(n.."/"..class..".aseprite"))
  assert(sprite.width==n and sprite.height==n and #sprite.frames==2 and #sprite.layers==4)
  sprite:close()
  for _,pose in ipairs({"idle","attack"}) do
    local image=Image{fromFile=path(n.."/"..class.."-"..pose..".png")}
    assert(image.width==n and image.height==n)
    local occupied=0
    for pixel in image:pixels() do
      local alpha=app.pixelColor.rgbaA(pixel())
      assert(alpha==0 or alpha==255,"Unexpected antialiasing")
      if alpha==255 then occupied=occupied+1 end
    end
    assert(occupied>n*n/6,"Sprite is blank or too small")
  end
end end
print("Verified: 24 pixel-native poses; 12 two-frame, four-layer Aseprite files; 36/64/128px.")
local report=assert(io.open(path("verification.txt"),"w"))
report:write("PASS: 24 native-sized transparent PNG poses, binary alpha only.\n")
report:write("PASS: 12 Aseprite files reopened; two frames and four layers each.\n")
report:write("Sizes: 36x36, 64x64, 128x128.\n")
report:close()
