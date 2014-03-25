#!/usr/bin/env python 
#
# This file is protected by Copyright. Please refer to the COPYRIGHT file distributed with this 
# source distribution.
# 
# This file is part of REDHAWK Basic Components freqfilter.
# 
# REDHAWK Basic Components freqfilter is free software: you can redistribute it and/or modify it under the terms of 
# the GNU Lesser General Public License as published by the Free Software Foundation, either 
# version 3 of the License, or (at your option) any later version.
# 
# REDHAWK Basic Components freqfilter is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; 
# without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR 
# PURPOSE.  See the GNU Lesser General Public License for more details.
# 
# You should have received a copy of the GNU Lesser General Public License along with this 
# program.  If not, see http://www.gnu.org/licenses/.
#
#
# AUTO-GENERATED
#
# Source: freqfilter.spd.xml
# Generated on: Mon Feb 25 15:37:23 EST 2013
# Redhawk IDE
# Version:R.1.8.2
# Build id: v201212041901
from ossie.resource import Resource, start_component
import logging
import threading

import math
from scipy.signal import lfiltic, lfilter, iirdesign

from freqfilter_base import * 

def convertCmplx(input):
    """Convert a real list into a python complex list of 1/2 the size
    """
    out=[]
    for i in xrange(len(input)/2):
        out.append(complex(input[2*i], input[2*i+1]))
    return out

def demuxCxData(cxInput):
    out=[]
    for val in cxInput:
        out.append(val.real)
        out.append(val.imag)
    return out

def isCmpxl(vec):
    """Check to see if there is any substantial imaginary component left in the vector
    """
    real =0.0
    imag = 0.0
    for val in vec:
        if isinstance(val,complex):
            real+=abs(val.real)
            imag+=abs(val.imag)
        else:
            real+=abs(val)
    
    return (imag/(real+imag)>1e-5) #arbitrary threshold for whether or not data is no longer complex  


class FilterState(object):
    """Encapsulate the filter state here to make the filter scalable for multiple streamIDs
    """
    MAX_BUFFER_LEN = 8*1024
    def __init__(self):
        
        self.newFilterLock = threading.Lock()        
        self.newFilter = None
        self.zi=None
        self.outputCmplx=None
        self.lastX = []
        self.lastY = []
        self.xdelta = None
        self.a = self.b=[]
        self.filterComplex=None
        self.filterProps=None

    def setNewFilter(self, newFilter):
        self.newFilterLock.acquire()
        self.newFilter = newFilter
        self.newFilterLock.release()

    def process(self, data,sri, T):
        #store off newFilter value now to keep from race condition in case someone updates us
        self.newFilterLock.acquire()
        newFilter = self.newFilter
        self.newFilter=None
        self.newFilterLock.release()
        
        #initial conidition for internal variable for this process block
        sriPush=False        
        #look for xdelta change
        if sri.xdelta != self.xdelta:
            sriPush=True
            self.xdelta = sri.xdelta
            #our history is invalid (it would have to be resampled to be valid)
            #clear it out and star afresh
            self.lastX = self.lastY=[]
            self.zi=None
            #if the sample rate changed and filterProps
            #we must redesign our taps to stay up to date with the new rate
            if self.filterProps!=None and newFilter==None:
                newFilter = self.filterProps
                      
        #take care of doing a new filter update
        if newFilter !=None:
            if isinstance(newFilter, tuple):
                self.a, self.b, self.filterComplex = newFilter
                self.filterProps=None
            else:
                self.filterProps = newFilter
                #set self.a, self.b, and filterComplex in the designFilter method
                self._designFilter()
            #reset our state to None so we will calculate it later
            self.zi=None

        #if we don't have any history - calculate it for this set of filter coeficients 
        if self.zi==None:
            #get new initial conditions -- only use the final elements from our old data
            M = len(self.b)-1
            N = len(self.a)-1
            self.zi = lfiltic(self.b,self.a,self.lastY[-M:], self.lastX[-N:])

        #deal with complexity of output as a function of input complexity and filter state complexity
        inputCmplx = sri.mode==1
        if inputCmplx:
            #convert the data to be complex
            data = convertCmplx(data)
            outputCmplx=True    
        elif self.filterComplex:
            outputCmplx = True
        elif self.outputCmplx:
            #if input is not complex and filter is not complex and the output was complex
            # check if the complexity has worked its way out of the iir state
            # data remains complex only if the intial conditions reamin complex
            outputCmplx = isCmpxl(self.zi)
        else:
            #if all are real - then the output is also real
            outputCmplx=False
         
        #deal with output changing complexity
        if outputCmplx != self.outputCmplx:
            #force SRI push
            sriPush=True
            self.outputCmplx = outputCmplx
            if not self.outputCmplx and self.zi!=None:
                #take the real part of all of our history because the output is no longer complex
                self.zi = [x.real for x in self.zi]

        #now update the sri.mode to reflect the state of the output
        if outputCmplx:
            sri.mode = 1
        else:
            sri.mode=0
                    
        #here is the actual filter operation courtesy of scipy
        if self.zi!=[]:
            #this is the typical case
            output, self.zi = lfilter(self.b,self.a,data,zi=self.zi)
        else:
            #this is a corner case if the user has configured us so that no filtering is necessary!
            output = lfilter(self.b,self.a,data)
        
        historyLen = max(self.MAX_BUFFER_LEN, len(self.zi))
        #store history for next go in case we need to remake our filter 
        self.lastX.extend(data)
        if len(self.lastX) > historyLen:
            self.lastX = self.lastX[-historyLen:]
        
        self.lastY.extend(output)
        if len(self.lastY) > historyLen:
            self.lastY = self.lastY[-historyLen:]
        
        if self.outputCmplx:
            output = demuxCxData(output)
        else:
            output = list(output)
        
        return sriPush, output

    def _designFilter(self):
        """design IIR filter coeficients with the iirdesign method
        """
        wTransition= self.filterProps.TransitionWidth*self.xdelta
        #this took long to figure out then I'd like to admit
        #the gain gainStop is the typical conversion
        #but the passband gain is measured from 0 instead of the ripple from 1
        #so we have to do 1-Val to get the bound on the ripple from the desired value
        gainStop = -20*math.log10(self.filterProps.Ripple)
        gainPass = -20*math.log10(1-self.filterProps.Ripple)
        f1Norm= self.filterProps.freq1*self.xdelta*2.0
        if self.filterProps.Type in ('bandpass','bandstop'):
            wfreqs = [f1Norm,  self.filterProps.freq2*self.xdelta*2.0]
            wfreqs.sort()
        if self.filterProps.filterComplex and self.filterProps.Type in ('bandpass','bandstop'):
            #for the compelx types - design a low version of the filter.  Then modulate it to the 
            #correct output center frequency by multiplying the taps a complex tuner exponential
            self.filterComplex = True
            #design a low pass filter then modulate the FIR part up
            w1 = (wfreqs[1] - wfreqs[0])/2.0
            w2 = w1+ wTransition
            if self.filterProps.Type=='bandpass':
                wp = w1
                ws = w2
            else:
                wp = w2
                ws = w1
        else:
            self.filterComplex = False
            if self.filterProps.Type in ('lowpass', 'highpass'):
                w1 = f1Norm
                w2 = w1+wTransition

            else:
                w1 = wfreqs
                w2 = [w1[0]-wTransition, w1[1]+wTransition]
                                    
            if self.filterProps.Type in ('lowpass', 'bandpass'):
                wp=w1
                ws=w2
            else:
                wp=w2
                ws=w1

        try:
            self.b, self.a = iirdesign(wp,ws,gstop=gainStop,gpass=gainPass, output='ba')
        except Exception, e:
            print "WARNING - IIRDESIGN HAS FAILED!"
            print e
            print "wp = ", wp, 
            print "ws = ", ws
            print "gainStop = ", gainStop
            print "gpass = ", gainPass
            print "freq1", self.filterProps.freq1
            print "freq1", self.filterProps.freq2
            print "xdelta = ", self.xdelta
            self.a=[1]
            self.b=[1]
        if self.filterComplex:
            #multiply the designed taps by the output frequency
            wc = sum(wfreqs)*math.pi/2.0
            bTuned = []
            aTuned = []
            tuner=0
            for aval, bval in zip(self.a,self.b):
                cxTuner = complex(math.cos(tuner),math.sin(tuner))
                aTuned.append(aval*cxTuner)
                bTuned.append(bval*cxTuner)
                tuner +=wc
            self.a = aTuned
            self.b = bTuned

class freqfilter_i(freqfilter_base):
    """Freq filter implements a direct form 2 FIR/IIR real or complex tap filter leveraging scipy.signal lfilter.
       Please see scipy for complete documentation
       For here - it is enough to know the following:
       "a" represents the "IIR" part - set a = [1] for a purely FIR filter implementation
       "b" represents the "FIR" part - set b = [1] for a purely IIR filter implementation
       "aCmplx" and "bCmplx" is used to represent whether or not the filter taps should be interpreted as complex
    
        A word to the wise about complex in/out/taps conditions
        the output will be complex if the input is complex or aCmplx or bCmplx are set
        
        It is possible to change between complex input & output and complex taps.  Things should work
        -- but it may take a while to get the output to shift from complex back to real as 
        you need to let the complex energy work its way through the filter
    
    """
    
    def initialize(self):
        """
        This is called by the framework immediately after your component registers with the NameService.
        """
        freqfilter_base.initialize(self)
        self.state={}
        self._a=self._b=[]
        self.manualTaps=False
        self._filterComplex=False
        self.newFilterPropLock = threading.Lock() 
    
    def _rebuildManual(self):        
        """rebuild the filter initial condition based upon current state
        """
        if self.manualTaps:
            aComplex =isCmpxl(self.a)
            bComplex =isCmpxl(self.b)
            self._filterComplex = aComplex or aComplex
            if aComplex:
                self._a = self.a[:]
            else:
                self._a=[x.real for x in self.a]
            if bComplex:
                self._b = self.b[:]
            else:
                self._b=[x.real for x in self.b]

    def process(self):
        """Main process loop
        """
        data, T, EOS, streamID, sri, sriChanged, inputQueueFlushed = self.port_dataFloat_in.getPacket()
        #cache these guys off here in case there are changed mid process loop
        if inputQueueFlushed:
            self._log.warning("inputQueueFlushed - state reset")
            self.state={}
            
        if data == None:
            return NOOP
        
        #get the state from the streamID or create a new state instance for a new streamID
        if self.state.has_key(streamID):
            state = self.state[streamID]
        else:
            self._log.debug("got new streamID  %s"%streamID)
            state = FilterState()
            self.newFilterPropLock.acquire()
            self.state[streamID]= state
            if self.manualTaps:
                state.setNewFilter((self._a,self._b, self._filterComplex))
            else:
                state.setNewFilter(self.filterProps)
            self.newFilterPropLock.release()
        
        forceSriUpdate, outData = state.process(data,sri, T)
        if forceSriUpdate or sriChanged:
            self._log.debug("pushing output sri %s"%streamID)
            self.port_dataFloat_out.pushSRI(sri)
        #finally get to push the output
        self.port_dataFloat_out.pushPacket(outData, T, EOS, streamID)
        #if we are done with this stream then pop off the state
        if EOS:
            self.state.pop(streamID)
        return NORMAL

    def configure(self, configProperties):
        """override base class
        """
        abConfigured = any([prop.id in ("a", "b") for prop in configProperties])
        filterPropsConfigured = any([prop.id =='filterProps'for prop in configProperties])
        if self._started and abConfigured and filterPropsConfigured:
            raise CF.PropertySet.InvalidConfiguration("Cannot configure filterProps and taps simultaniously", configProperties)
        freqfilter_base.configure(self, configProperties)
        #check to see if we need to update our filter props
        if filterPropsConfigured:
            self._log.debug("filterPropsConfigured")
            self.newFilterPropLock.acquire()
            self.manualTaps=False
            self.a = []
            self.b = []
            for state in self.state.values():
                state.setNewFilter(self.filterProps)                      
            self.newFilterPropLock.release()
                
        elif abConfigured:
            self._log.debug("abConfigured")
            self.newFilterPropLock.acquire()
            self.manualTaps=True
            self._rebuildManual()       
            for state in self.state.values():
                state.setNewFilter((self._a,self._b, self._filterComplex))
            self.newFilterPropLock.release()
  
if __name__ == '__main__':
    logging.getLogger().setLevel(logging.WARN)
    logging.debug("Starting Component")
    start_component(freqfilter_i)
