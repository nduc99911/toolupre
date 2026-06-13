import sqlite3, os
conn = sqlite3.connect('storage/reupmaster.db')
c = conn.cursor()
c.execute("SELECT id, original_path, processed_path, status FROM videos ORDER BY rowid DESC LIMIT 3")
for r in c.fetchall():
    vid, orig, proc, status = r
    print(f"ID: {vid} | status: {status}")
    print(f"  orig: {orig}")
    print(f"    isdir={os.path.isdir(orig or '')} isfile={os.path.isfile(orig or '')}")
    print(f"  proc: {proc}")
    print(f"    isdir={os.path.isdir(proc or '')} isfile={os.path.isfile(proc or '')}")
    if orig and os.path.isdir(orig):
        print(f"    orig files: {os.listdir(orig)[:5]}")
    if proc and os.path.isdir(proc):
        print(f"    proc files: {os.listdir(proc)[:5]}")
    if orig and os.path.isfile(orig):
        print(f"    orig is a FILE: {orig}")
    if proc and os.path.isfile(proc):
        print(f"    proc is a FILE: {proc}")
    print()
conn.close()
