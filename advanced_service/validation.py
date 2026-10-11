"""Bounded, strict multipart and request validation without model dependencies."""
from email import policy
from email.parser import BytesParser
import math
from registry import EXPERTS

MAX_BODY = 80 * 1024 * 1024
FILE_FIELDS = {'image', 'driving'}
TEXT_FIELDS = {'expert','model','prompt','steps','seed','width','height','frames','fps','max_tokens','guidance'}

def multipart(content_type, body):
    if not content_type.startswith('multipart/form-data;') or '\r' in content_type or '\n' in content_type:
        raise ValueError('Expected multipart/form-data')
    msg = BytesParser(policy=policy.default).parsebytes(
        f'Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n'.encode('ascii') + body)
    if not msg.is_multipart():
        raise ValueError('Malformed multipart upload')
    fields, files = {}, {}
    parts = list(msg.iter_parts())
    if len(parts) > len(FILE_FIELDS | TEXT_FIELDS):
        raise ValueError('Too many form fields')
    for part in parts:
        name = part.get_param('name', header='content-disposition')
        if part.is_multipart() or part.get_content_disposition() != 'form-data' or name not in FILE_FIELDS | TEXT_FIELDS:
            raise ValueError('Unknown form field')
        if name in fields or name in files:
            raise ValueError('Duplicate form field')
        data = part.get_payload(decode=True) or b''
        if name in FILE_FIELDS:
            files[name] = data
        elif len(data) > 16000:
            raise ValueError('Text field too long')
        else:
            fields[name] = data.decode('utf-8')
    return fields, files

def validate(fields, files):
    if set(fields) - TEXT_FIELDS or set(files) - FILE_FIELDS:
        raise ValueError('Unknown request field')
    if fields.get('expert') and fields.get('model') and fields['expert'] != fields['model']:
        raise ValueError('Conflicting expert and model')
    expert = fields.get('expert', fields.get('model', ''))
    if expert not in EXPERTS:
        raise ValueError('Unknown expert')
    info = EXPERTS[expert]
    result = dict(info['defaults'], expert=expert)
    prompt = str(fields.get('prompt', '')).strip()
    if len(prompt) > 4000 or (not prompt and expert != 'liveportrait'):
        raise ValueError('Prompt must contain 1–4000 characters')
    result['prompt'] = prompt
    for name, bounds in {'steps':(1,60), 'seed':(0,2147483647), 'width':(256,1536),
            'height':(256,768), 'frames':(9,49), 'fps':(1,30), 'max_tokens':(1,1024),
            'guidance':(0,20)}.items():
        if name not in fields:
            continue
        try:
            value = float(fields[name]) if name == 'guidance' else int(fields[name])
        except (ValueError, TypeError):
            raise ValueError(f'{name}: invalid number') from None
        if not math.isfinite(value) or not bounds[0] <= value <= bounds[1]:
            raise ValueError(f'{name}: allowed range {bounds[0]}–{bounds[1]}')
        result[name] = value
    for name, required, limit in [('image', info['requires_image'], 12*1024*1024),
                                  ('driving', info['requires_driving'], 64*1024*1024)]:
        value = files.get(name)
        if required and not value:
            raise ValueError(f'{name}: required for {expert}')
        if value is not None and (not value or len(value) > limit):
            raise ValueError(f'{name}: file too large or empty')
    if 'driving' in files and expert != 'liveportrait':
        raise ValueError('Driving video is only supported by LivePortrait')
    if 'image' in files and not (info['requires_image'] or expert == 'flux-klein'):
        raise ValueError('This expert does not accept an image')
    if expert in {'controlnet-canny', 'multidiffusion'}:
        if result['width'] % 8 or result['height'] % 8:
            raise ValueError('Image dimensions must be multiples of 8')
        if expert == 'controlnet-canny' and max(result['width'],result['height']) > 768:
            raise ValueError('ControlNet CPU dimensions are limited to 768')
    if expert in {'flux-klein','ltx-video'} and (result['width'] % 32 or result['height'] % 32):
        raise ValueError('Dimensions must be multiples of 32')
    if expert == 'ltx-video' and (result['frames']-1) % 8:
        raise ValueError('LTX frame count must be 8n+1 (9, 17, 25, 33, 41, 49)')
    if expert == 'cogvideox' and (result['width'],result['height'],result['frames']) != (720,480,49):
        raise ValueError('This CogVideoX I2V adapter uses 720×480 and 49 frames')
    return result
