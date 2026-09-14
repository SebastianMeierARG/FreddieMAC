import nbformat, sys, time
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

nb = nbformat.read("notebook/IFRS9_PD_Pipeline.ipynb", as_version=4)
client = NotebookClient(nb, timeout=900, kernel_name="python3",
                        resources={"metadata": {"path": "notebook"}})
t0 = time.time()
status = "OK"
errtext = ""
try:
    client.execute()
except CellExecutionError as e:
    status = "FAILED"
    errtext = str(e)
finally:
    nbformat.write(nb, "notebook/IFRS9_PD_Pipeline.ipynb")

out_path = r"C:\Users\sebat\Tesis Maestria\data\FreddieMAC\_nbexec_result.txt"
with open(out_path, "w", encoding="utf-8") as f:
    f.write(f"STATUS: {status}\n")
    f.write(f"ELAPSED_MIN: {(time.time()-t0)/60:.1f}\n")
    f.write(errtext[:6000])

print("DONE", status)
