# %% Import library
from obspy.clients.seedlink.easyseedlink import EasySeedLinkClient

RS3D_HOST = "169.254.221.62:18000"
NETWORK = "AM"
STATION = "R77A7"

def on_data(trace):
    """
    Extracts the data from the trace and prints it to the console.
    """
    ID = trace.id
    time = trace.stats.starttime
    samples = trace.stats.npts
    sampling_rate = trace.stats.sampling_rate
    print(f"channel id: {ID}, \nTime: {time}, \nSamples: {samples}, \nSampling Rate: {sampling_rate} Hz", flush=True)

if __name__ == "__main__":
    # Create a client without auto-connecting: obspy's SeedLinkConnection
    # defaults to timeout=None, which crashes in connect() (obspy 1.5.1)
    client = EasySeedLinkClient(RS3D_HOST, autoconnect=False)
    client.on_data = on_data
    client.conn.timeout = 10  # Set timeout to 10 seconds
    client.connect()  # Connect to the SeedLink server

    channels = ["EHZ", "EHN", "EHE"]
    for channel in channels:
        client.select_stream(NETWORK, STATION, channel)

    print("Listening for data from RS3D...", flush=True)
    client.run()
# %%
