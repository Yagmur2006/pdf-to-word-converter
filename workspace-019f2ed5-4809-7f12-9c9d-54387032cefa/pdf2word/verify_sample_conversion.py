import os
import uuid
import json
import time
import http.cookiejar
import urllib.request
import urllib.error
from pathlib import Path

base_url = 'http://127.0.0.1:8000'
workspace = Path('.')
pdf_path = workspace / 'sample-test.pdf'
docx_path = workspace / 'sample-test.docx'

objects = []
objects.append(b'%PDF-1.1')
objects.append(b'1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj')
objects.append(b'2 0 obj\n<< /Type /Pages /Count 1 /Kids [3 0 R] >>\nendobj')
objects.append(b'3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj')
objects.append(b'4 0 obj\n<< /Length 33 >>\nstream\nBT /F1 24 Tf 50 100 Td (Hello PDF) Tj ET\nendstream\nendobj')
objects.append(b'5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj')
content = b'\n'.join(objects) + b'\n'
lines = content.split(b'\n')
offs = []
pos = 0
for line in lines:
    offs.append(pos)
    pos += len(line) + 1
xref_lines = [b'xref', b'0 6', b'0000000000 65535 f ']
for o in offs[1:]:
    xref_lines.append(f'{o:010d} 00000 n '.encode('ascii'))
trailer = b'trailer\n<< /Root 1 0 R /Size 6 >>\nstartxref\n' + str(pos).encode('ascii') + b'\n%%EOF\n'
pdf_bytes = content + b'\n'.join(xref_lines) + b'\n' + trailer
pdf_path.write_bytes(pdf_bytes)

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

req = urllib.request.Request(base_url + '/api/csrf.php', headers={'Accept': 'application/json'})
with opener.open(req, timeout=20) as resp:
    data = json.load(resp)
    token = data['data']['csrfToken']
print('CSRF token fetched.')

boundary = uuid.uuid4().hex
boundary_bytes = boundary.encode('ascii')
body = b''.join([
    b'--' + boundary_bytes + b'\r\n',
    b'Content-Disposition: form-data; name="file"; filename="sample-test.pdf"\r\n',
    b'Content-Type: application/pdf\r\n\r\n',
    pdf_bytes,
    b'\r\n--' + boundary_bytes + b'--\r\n',
])
headers = {
    'Content-Type': f'multipart/form-data; boundary={boundary}',
    'Content-Length': str(len(body)),
    'X-CSRF-Token': token,
}
req = urllib.request.Request(base_url + '/api/upload.php', method='POST', data=body, headers=headers)
with opener.open(req, timeout=120) as resp:
    result = json.load(resp)
job_id = result['data']['jobId']
print('Upload successful. jobId =', job_id)

status = None
for attempt in range(60):
    req = urllib.request.Request(base_url + f'/api/status.php?jobId={job_id}', headers={'Accept': 'application/json'})
    with opener.open(req, timeout=20) as resp:
        status = json.load(resp)['data']
    print(f'[{attempt}] state={status.get("state")} progress={status.get("progress")} message={status.get("message")}')
    if status.get('state') in ('done', 'error'):
        break
    time.sleep(1)

if status is None:
    raise RuntimeError('No status response received.')
if status.get('state') != 'done':
    raise RuntimeError(f'Conversion failed or timed out: {status}')

req = urllib.request.Request(base_url + f'/api/download.php?jobId={job_id}')
with opener.open(req, timeout=120) as resp:
    content = resp.read()
    docx_path.write_bytes(content)
print('Download complete:', docx_path)
print('Downloaded file size:', len(content))
