import subprocess

# Exe name and load key.
processname = 'mednafen'
xdotoolkey = 'F7'

proc = subprocess.Popen('xdotool search --classname '+processname, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
res = proc.communicate()[0] #   Return result and end process.
res = res[:-1]
windowid = res.decode('ascii')

proc3 = subprocess.Popen('xdotool keydown --window '+ windowid + ' ' + xdotoolkey, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
res = proc3.communicate()[0] #  ..
proc4 = subprocess.Popen('xdotool keyup --window '+ windowid + ' ' + xdotoolkey, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
res = proc4.communicate()[0] #  ..
