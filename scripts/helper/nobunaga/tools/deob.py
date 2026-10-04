"""Undo the DNAS2 library's in-place code obfuscation, offline.

Each protected function starts with a guard: if the word at body-0x14 is 0, call
stub(body, len^key, key, flags) which transforms the words of [body, body+len)
and sets the guard. The stub derives a nibble program from the key, and each
step applies one of eight word transforms to every word whose offset (from
body - a) is not in a per-site skip list found through `flags` in a table.
"""
import struct, sys

M=0xffffffff
def ror(w,n): return ((w>>n)|(w<<(32-n)))&M
def perm(w):
    b0,b1,b2,b3=w&0xff,(w>>8)&0xff,(w>>16)&0xff,(w>>24)&0xff
    return (b0<<8)|(b3<<16)|b2|(b1<<24)
X1,X2=0x09f8ed17,0xa95128c3
TRANSFORMS=[
    lambda w: w^X1,
    lambda w: w^X2,
    lambda w: ror(w,13),
    lambda w: ror(w,8),
    perm,
    lambda w: ror(w^X1,13),
    lambda w: ror(perm(w)^X2,8),
    lambda w: perm(ror(ror(w^X1,8),13)),
]
def program(key):
    n=(key>>28)&0xf
    n = 5 if (n&7)==0 else (n&0xf)-(n&8)
    p=0
    for i in range(7): p |= ((key>>(4*i))&7)<<(4*i)
    return (p&0x0fffffff)|(n<<28)

class Image:
    def __init__(self, data, base, foff=0):
        self.d=bytearray(data); self.base=base; self.foff=foff
    def off(self,va): return va-self.base+self.foff
    def u32(self,va): return struct.unpack_from("<I",self.d,self.off(va))[0]
    def set32(self,va,v): struct.pack_into("<I",self.d,self.off(va),v&M)

def lookup(img, table, flags):
    """FUN_00290c80: (a, count, list) for this flags value, or (0,0,[])."""
    if flags==0: return 0,0,[]
    cnt=img.u32(table)
    for i in range(cnt):
        idv=img.u32(table+4+8*i); off=img.u32(table+8+8*i)
        if idv>>1 == flags>>1:
            blk=table+4+cnt*8+off
            a=img.u32(blk); n=img.u32(blk+4)
            lst=[img.u32(blk+8+4*j) for j in range(n)]
            return a,n,lst
    return 0,0,[]

def deob_site(img, body, key, lenx, flags, table, transforms=TRANSFORMS):
    length=(lenx^key)&M
    assert flags&1==0, "reverse variant not handled"
    a,n,lst=lookup(img, table, flags)
    aux=body-a
    skip=set(lst)
    prog=program(key); steps=prog>>28
    for i in range(steps):
        t=transforms[(prog>>(4*i))&0xf]
        for va in range(body, body+length, 4):
            if n>0 and (va-aux)&M in skip: continue
            img.set32(va, t(img.u32(va)))
    return length

def find_sites(img, stub, lo, hi):
    """Every `jal stub` with the guard's lui/addiu $v1 pair before it."""
    jal=0x0c000000|((stub>>2)&0x03ffffff)
    sites=[]
    for va in range(lo, hi, 4):
        if img.u32(va)!=jal: continue
        # walk back up to 16 words for lui $v1 / addiu $v1,$v1
        flag=None; hi_=None; lo_=None
        for back in range(1,20):
            w=img.u32(va-4*back)
            if (w>>16)==0x2463 and lo_ is None:      # addiu v1,v1,imm
                lo_=w&0xffff; lo_=lo_-0x10000 if lo_&0x8000 else lo_
            elif (w>>16)==0x3c03 and hi_ is None:    # lui v1,imm
                hi_=w&0xffff
            if hi_ is not None and lo_ is not None:
                flag=(hi_<<16)+lo_; break
        if flag is None: continue
        w1,w2,w3=img.u32(flag+4),img.u32(flag+8),img.u32(flag+12)
        sites.append((flag+0x14, w1, w2, w3))
    return sites

def run(img, stub, table, lo, hi, transforms=TRANSFORMS):
    out=[]
    for body,key,flags,lenx in find_sites(img, stub, lo, hi):
        n=deob_site(img, body, key, lenx, flags, table, transforms)
        out.append((body,n,flags))
    return out
