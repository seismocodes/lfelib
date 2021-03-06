"""
This module contains functions to find LFEs with the
temporary stations or with the permanent stations
using the templates from Plourde et al. (2015)
"""
import obspy
from obspy import read
from obspy import read_inventory
from obspy import UTCDateTime
from obspy.core.stream import Stream
from obspy.core.trace import Trace
from obspy.signal.cross_correlation import correlate

import matplotlib.pylab as pylab
import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd
import pickle

from datetime import timedelta
from math import ceil, cos, floor, pi

import argparse

# Relative package imports
from utils import correlate
from utils.get_data import get_from_IRIS, get_from_NCEDC

# data directory is relative to wherever script is run
DATADIR = os.path.join(os.getcwd(), 'data')

def clean_LFEs(index, times, meancc, dt, freq0):
    """
    This function takes all times where the
    cross-correlation is higher than a threshold
    and groups those that belongs to the same LFE

    Input:
        type index = 1D numpy array
        index = Indices where cc is higher than threshold
        type times = 1D numpy array
        times = Times where cc is computed
        type meancc = 1D numpy array
        meancc = Average cc across all channels
        type dt = float
        dt = Time step of the seismograms
        type freq0 = float
        freq0 = Maximum frequency rate of LFE occurrence
    Output:
        type time = 1D numpy array
        time = Timing of LFEs
        type cc = 1D numpy array
        cc = Maximum cc during LFE
    """
    # Initializations
    maxdiff = int(floor(1.0 / (dt * freq0)))
    list_index = [[index[0][0]]]
    list_times = [[times[index[0][0]]]]
    list_cc = [[meancc[index[0][0]]]]
    # Group LFE times that are close to each other
    for i in range(1, np.shape(index)[1]):
        if (index[0][i] - list_index[-1][-1] <= maxdiff):
            list_index[-1].append(index[0][i])
            list_times[-1].append(times[index[0][i]])
            list_cc[-1].append(meancc[index[0][i]])
        else:
            list_index.append([index[0][i]])
            list_times.append([times[index[0][i]]])
            list_cc.append([meancc[index[0][i]]])
    # Number of LFEs identified
    N = len(list_index)
    time = np.zeros(N)
    cc = np.zeros(N)
    # Timing of LFE is where cc is maximum
    for i in range(0, N):
        maxcc =  np.amax(np.array(list_cc[i]))
        imax = np.argmax(np.array(list_cc[i]))
        cc[i] = maxcc
        time[i] = list_times[i][imax]
    return(time, cc)

def fill_data(D, orientation, station, channels, reference):
    """
    Return the data that must be cross correlated with the template

    Input:
        type D = obspy Stream
        D = Data downloaded
        type orientation = list of dictionnaries
        orientation = azimuth, dip for 3 channels (for data)
        type station = string
        station = Name of station
        type channels = string
        channels = Names of channels
        type reference = list of dictionnaries
        reference = azimuth, dip for 3 channels (for template)
    Output:
        type data = list of obspy Stream
        data = Data to be analyzed with correct azimuth
    """
    # East-West channel
    EW = Stream()
    if (channels == 'EH1,EH2,EHZ'):
        if (len(D.select(channel='EH1')) > 0):
            EW = D.select(channel='EH1')
    else:
        if (len(D.select(component='E')) > 0):
            EW = D.select(component='E')
    # North-South channel
    NS = Stream()
    if (channels == 'EH1,EH2,EHZ'):
         if (len(D.select(channel='EH2')) > 0):
            NS = D.select(channel='EH2')
    else:
         if (len(D.select(component='N')) > 0):
            NS = D.select(component='N')
    # Vertical channel
    UD = Stream()
    if (channels == 'EH1,EH2,EHZ'):
        if (len(D.select(channel='EHZ')) > 0):
             UD = D.select(channel='EHZ')
    else:
         if (len(D.select(component='Z')) > 0):
            UD = D.select(component='Z')
    # Rotation of the data
    data = []
    if ((len(EW) > 0) and (len(NS) > 0) and (len(EW) == len(NS))):
        # Orientation of the data
        dE = orientation[0]['azimuth'] * pi / 180.0
        dN = orientation[1]['azimuth'] * pi / 180.0
        # Orientation of the template
        tE = reference[0]['azimuth'] * pi / 180.0
        tN = reference[1]['azimuth'] * pi / 180.0
        EWrot = Stream()
        NSrot = Stream()
        for i in range(0, len(EW)):
            if (len(EW[i].data) == len(NS[i].data)):
                EWrot0 = EW[i].copy()
                NSrot0 = NS[i].copy()
                EWrot0.data = cos(dE - tE) * EW[i].data + \
                              cos(dN - tE) * NS[i].data
                NSrot0.data = cos(dE - tN) * EW[i].data + \
                              cos(dN - tN) * NS[i].data
                EWrot0.stats.station = station
                EWrot0.stats.channel = 'E'
                NSrot0.stats.station = station
                NSrot0.stats.channel = 'N'
                EWrot.append(EWrot0)
                NSrot.append(NSrot0)
        data.append(EWrot)
        data.append(NSrot)
    if (len(UD) > 0):
        for i in range(0, len(UD)):
            UD[i].stats.station = station
            UD[i].stats.channel = 'Z'
        data.append(UD)
    return(data)

def find_LFEs(filename, stations, tbegin, tend, outputfile, TDUR=10.0, filt=(1.5, 9.0), \
        freq0=1.0, nattempts=2, waittime=5.0, draw=False, \
        type_threshold='MAD', threshold=0.0075):
    """
    Find LFEs with the temporary stations from FAME
    using the templates from Plourde et al. (2015)

    Input:
        type filename = string
        filename = Name of the template
        type stations = list of strings
        stations = name of the stations used for the matched-filter algorithm
        type tebgin = tuplet of 6 integers
        tbegin = Time when we begin looking for LFEs
        type tend = tuplet of 6 integers
        tend = Time we stop looking for LFEs
        type TDUR = float
        TDUR = Time to add before and after the time window for tapering
        type filt = tuple of floats
        filt = Lower and upper frequencies of the filter
        type freq0 = float
        freq0 = Maximum frequency rate of LFE occurrence
        type nattempts = integer
        nattempts = Number of times we try to download data
        type waittime = positive float
        waittime = Type to wait between two attempts at downloading
        type draw = boolean
        draw = Do we draw a figure of the cross-correlation?
        type type_threshold = string
        type_threshold = 'MAD' or 'Threshold'
        type threshold = float
        threshold = Cross correlation value must be higher than that
    Output:
        None
    """

    # Get the network, channels, and location of the stations
    staloc = pd.read_csv('station_locations.txt', \
        sep=r'\s{1,}', header=None, engine='python')
    staloc.columns = ['station', 'network', 'channels', 'location', \
        'server', 'latitude', 'longitude']

    # Create directory to store the LFEs times
    namedir = 'LFEs/' + filename
    if not os.path.exists(namedir):
        os.makedirs(namedir)

    # File to write error messages
    namedir = 'error'
    if not os.path.exists(namedir):
        os.makedirs(namedir)
    errorfile = 'error/' + filename + '.txt'

    # Read the templates
    templates = Stream()
    for station in stations:
        templatefile = 'templates/' + filename + '/' + station + '.pkl'
        with open(templatefile, 'rb') as f:
            data = pickle.load(f)
        if (len(data) == 3):
            EW = data[0]
            NS = data[1]
            UD = data[2]
            EW.stats.station = station
            NS.stats.station = station
            EW.stats.channel = 'E'
            NS.stats.channel = 'N'
            templates.append(EW)
            templates.append(NS)
        else:
            UD = data[0]
        UD.stats.station = station
        UD.stats.channel = 'Z'
        templates.append(UD)

    # Begin and end time of analysis
    t1 = UTCDateTime(year=tbegin[0], month=tbegin[1], \
        day=tbegin[2], hour=tbegin[3], minute=tbegin[4], \
        second=tbegin[5])
    t2 = UTCDateTime(year=tend[0], month=tend[1], \
        day=tend[2], hour=tend[3], minute=tend[4], \
        second=tend[5])

    # Read the data
    data = []
    for station in stations:
        # Get station metadata for downloading
        for ir in range(0, len(staloc)):
            if (station == staloc['station'][ir]):
                network = staloc['network'][ir]
                channels = staloc['channels'][ir]
                location = staloc['location'][ir]
                server = staloc['server'][ir]

        # Duration of template
        template = templates.select(station=station, component='Z')[0]
        dt = template.stats.delta
        nt = template.stats.npts
        duration = (nt - 1) * dt
        Tstart = t1 - TDUR
        Tend = t2 + duration + TDUR
        delta = t2 + duration - t1
        ndata = int(delta / dt) + 1

        # Orientation of template
        # Date chosen: January 1st 2020
        mychannels = channels.split(',')
        mylocation = location
        if (mylocation == '--'):
            mylocation = ''
        response = DATADIR + '/response/' + network + '_' + station + '.xml'
        inventory = read_inventory(response, format='STATIONXML')
        reference = []
        for channel in mychannels:
            angle = inventory.get_orientation(network + '.' + \
                station + '.' + mylocation + '.' + channel, \
                UTCDateTime(2020, 1, 1, 0, 0, 0))
            reference.append(angle)

        # First case: we can get the data from IRIS
        if (server == 'IRIS'):
            (D, orientation) = get_from_IRIS(station, network, channels, \
                location, Tstart, Tend, filt, dt, nattempts, waittime, \
                errorfile, DATADIR)
        # Second case: we get the data from NCEDC
        elif (server == 'NCEDC'):
            (D, orientation) = get_from_NCEDC(station, network, channels, \
                location, Tstart, Tend, filt, dt, nattempts, waittime, \
                errorfile, DATADIR)
        else:
            raise ValueError('You can only download data from IRIS and NCEDC')

        # Append data to stream
        if (type(D) == obspy.core.stream.Stream):
            stationdata = fill_data(D, orientation, station, channels, \
                reference)
            if (len(stationdata) > 0):
                for stream in stationdata:
                    data.append(stream)

    # Number of hours of data to analyze
    nhour = int(ceil((t2 - t1) / 3600.0))

    # Create dataframe to store LFE times
    df = pd.DataFrame(columns=['year', 'month', 'day', 'hour', \
        'minute', 'second', 'cc', 'nchannel'])

    # Loop on hours of data
    for hour in range(0, nhour):
        nchannel = 0
        Tstart = t1 + hour * 3600.0
        Tend = t1 + (hour + 1) * 3600.0 + duration
        delta = Tend - Tstart
        ndata = int(delta / dt) + 1

        # Loop on channels
        for channel in range(0, len(data)):
            # Cut the data
            subdata = data[channel]
            subdata = subdata.slice(Tstart, Tend)
            # Check whether we have a complete one-hour-long recording
            if (len(subdata) == 1):
                if (len(subdata[0].data) == ndata):
                    # Get the template
                    station = subdata[0].stats.station
                    component = subdata[0].stats.channel
                    template = templates.select(station=station, \
                        component=component)[0]
                    # Cross correlation
                    cctemp = correlate.optimized(template, subdata[0])
                    if (nchannel > 0):
                        cc = np.vstack((cc, cctemp))
                    else:
                        cc = cctemp
                    nchannel = nchannel + 1

        if (nchannel > 0):

            # Compute average cross-correlation across channels
            meancc = np.mean(cc, axis=0)
            if (type_threshold == 'MAD'):
                MAD = np.median(np.abs(meancc - np.mean(meancc)))
                index = np.where(meancc >= threshold * MAD)
            elif (type_threshold == 'Threshold'):
                index = np.where(meancc >= threshold)
            else:
                raise ValueError('Type of threshold must be MAD or Threshold')
            times = np.arange(0.0, np.shape(meancc)[0] * dt, dt)

            # Get LFE times
            if np.shape(index)[1] > 0:
                (time, cc) = clean_LFEs(index, times, meancc, dt, freq0)

                # Add LFE times to dataframe
                i0 = len(df.index)
                for i in range(0, len(time)):
                    timeLFE = Tstart + time[i]
                    df.loc[i0 + i] = [int(timeLFE.year), int(timeLFE.month), \
                        int(timeLFE.day), int(timeLFE.hour), \
                        int(timeLFE.minute), timeLFE.second + \
                        timeLFE.microsecond / 1000000.0, cc[i], nchannel]

            # Draw figure
            if (draw == True):
                params = {'xtick.labelsize':16,
                          'ytick.labelsize':16}
                pylab.rcParams.update(params)
                plt.figure(1, figsize=(20, 8))
                if np.shape(index)[1] > 0:
                    for i in range(0, len(time)):
                        plt.axvline(time[i], linewidth=2, color='grey')
                plt.plot(np.arange(0.0, np.shape(meancc)[0] * dt, \
                    dt), meancc, color='black')
                if (type_threshold == 'MAD'):
                    plt.axhline(threshold * MAD, linewidth=2, color='red', \
                        label = '{:6.2f} * MAD'.format(threshold))
                elif (type_threshold == 'Threshold'):
                    plt.axhline(threshold, linewidth=2, color='red', \
                        label = 'Threshold = {:8.4f}'.format(threshold))
                else:
                    raise ValueError( \
                        'Type of threshold must be MAD or Threshold')
                plt.xlim(0.0, (np.shape(meancc)[0] - 1) * dt)
                plt.xlabel('Time (s)', fontsize=24)
                plt.ylabel('Cross-correlation', fontsize=24)
                plt.title('Average cross-correlation across stations', \
                    fontsize=30)
                plt.legend(loc=2, fontsize=24)
                plt.savefig('LFEs/' + filename + '/' + \
                    '{:04d}{:02d}{:02d}_{:02d}{:02d}{:02d}'.format( \
                    Tstart.year, Tstart.month, Tstart.day, Tstart.hour, \
                    Tstart.minute, Tstart.second) + '.png', format='png')
                plt.close(1)

    # Add to pandas dataframe and save
    df_all = df
    df_all = df_all.astype(dtype={'year':'int32', 'month':'int32', \
        'day':'int32', 'hour':'int32', 'minute':'int32', \
        'second':'float', 'cc':'float', 'nchannel':'int32'})
    df_all.to_csv('LFEs/' + filename + '/' + outputfile)

def cli():
    """Command line parser."""
    parser = argparse.ArgumentParser( \
        description='Find LFEs using the templates from Plourde et al')
    parser.add_argument('-t', type=str, dest='filename', \
        required=True, \
        help='Name of the template')
    parser.add_argument('-s', type=str, nargs='+', dest='stations', \
        required=True, \
        help='name of the stations used for the matched-filter algorithm')
    parser.add_argument('-t0', type=int, nargs='+', dest='tbegin', \
        required=True, \
        help='Time when we begin looking for LFEs')
    parser.add_argument('-tf', type=int, nargs='+', dest='tend', \
        required=True, \
        help='Time we stop looking for LFEs')
    parser.add_argument('-td', type=float, dest='TDUR', default=10.0, \
        required=False, \
        help='Time to add before and after the time window for tapering')
    parser.add_argument('-f', type=float, nargs='+', dest='filt',  \
        default=[1.5, 9.0], required=False, \
        help='Lower and upper frequencies of the filter')
    parser.add_argument('-f0', type=float, dest='freq0',  default=1.0, \
        required=False, \
        help='Maximum frequency rate of LFE occurrence')
    parser.add_argument('-n', type=int, dest='nattempts', default=10, \
        required=False,
        help='Number of times we try to download data')
    parser.add_argument('-w', type=float, dest='waittime', default=10.0, \
        required=False, \
        help='Time to wait between two attempts at downloading')
    parser.add_argument('-d', action='store_true', dest='draw', default=False, \
        required=False, \
        help='Do we draw a figure of the cross-correlation?')
    parser.add_argument('-tr', choices=['MAD','Threshold'], \
        dest='type_threshold', default='MAD', required=False, \
        help='Threshold type')
    parser.add_argument('-tv', type=float, dest='threshold', default=8, \
        required=False, \
        help='Threshold value')
    parser.add_argument('-o', type=str, dest='outputfile', default='results.csv', \
        required=True, \
        help='Name of outputfile')

    args = parser.parse_args()
    print(args)
    find_LFEs(args.filename, args.stations, args.tbegin, args.tend, args.outputfile, args.TDUR, \
        args.filt, args.freq0, args.nattempts, args.waittime, args.draw, \
        args.type_threshold, args.threshold)

if __name__ == '__main__':
    cli()
