import socket

found = False
for i in range(1, 255):
    ip = f"192.168.0.{i}"
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    result = sock.connect_ex((ip, 8481))
    sock.close()
    
    if result == 0:
        print(f"✓ FOUND API SERVER: {ip}:8481")
        found = True
    
    # Progress indicator
    if i % 50 == 0:
        print(f"  Scanned {i}/254 IPs...")

if not found:
    print("No API server found on port 8481 in 192.168.0.x network")
else:
    print("found IP!")
