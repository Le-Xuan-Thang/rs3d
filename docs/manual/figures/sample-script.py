from obspy import Stream, UTCDateTime
from obspy.clients.filesystem.sds import Client

client = Client('/home/you/.local/share/rs3d/sds')
start = UTCDateTime('2026-10-15T03:00:00.000000Z')
end = UTCDateTime('2026-10-15T04:00:00.000000Z')

st = Stream()
for channel in ('EHZ', 'EHN', 'EHE'):
    st += client.get_waveforms('AM', 'DEMO1', '00', channel, start, end)
st.trim(start, end)

st.detrend("demean")
st.filter("bandpass", freqmin=1.0, freqmax=10.0, corners=4, zerophase=True)

print(st)
