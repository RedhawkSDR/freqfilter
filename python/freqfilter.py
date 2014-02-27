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

from scipy.signal import lfiltic, lfilter

from freqfilter_base import * 

class FilterState(object):
    """Encapsolate the filter state here to make the filter scalable for multiple streamIDs
    """
    def __init__(self):
        
        self.zi=None
        self.outputCmplx=None
        self.lastX = []
        self.lastY = []
        self.updateFilter=True
        self.inputCmplx=None
        self.forceSriUpdate=True
        
    def _applyNewFilterChanges(self, a, b, stateCmplx):
        """ apply filter changes 
        """
        #set up the initial conditions based up on our filters and our history
        self.zi = lfiltic(b,a,self.lastY, self.lastX)
        
        oldOutputCmplx = self.outputCmplx
        #if the taps are complex or the initial condition is complex we will be complex
        if stateCmplx:
            self.outputCmplx = True  
        #if we are changing between real and complex modes force an sri update to reflect this 
        if (oldOutputCmplx != self.outputCmplx):
            self.forceSriUpdate = True
        self.updateFilter=False

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
        you need to let the complex energy work its way threw the filter
    
    """
    
    def initialize(self):
        """
        This is called by the framework immediately after your component registers with the NameService.
        """
        freqfilter_base.initialize(self)
        self.state={}
        self._rebuildFilter()
    
    def _isCmpxl(self, vec):
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
    
    def _rebuildFilter(self):        
        """rebuild the filter initial condition based upon current state
        """
        if self.aCmplx:
            self._a = self._convertCmplx(self.a)
        else:
            self._a = self.a
        if self.bCmplx:
            self._b = self._convertCmplx(self.b)
        else:
            self._b = self.b
        
    def _convertCmplx(self, input):
        """Convert a real list into a python complex list of 1/2 the size
        """
        out=[]
        for i in xrange(len(input)/2):
            out.append(complex(input[2*i], input[2*i+1]))
        return out

    def _updateSRI(self, sri):
        """Update the sri as appropriate and send out an sri packet
        """
        state = self.state[sri.streamID]
        state.inputCmplx = (sri.mode==1)
        if state.inputCmplx:
            state.outputCmplx = True
        if state.outputCmplx:
            sri.mode=1
        state.forceSriUpdate=False
        self.port_dataFloat_out.pushSRI(sri)

    def process(self):
        """Main process loop
        """
        data, T, EOS, streamID, sri, sriChanged, inputQueueFlushed = self.port_dataFloat_in.getPacket()
        #cache these guys off here in case there are changed mid process loop
            
        if data == None:
            return NOOP
        
        #get the state from the streamID or create a new state instance for a new streamID
        if self.state.has_key(streamID):
            state = self.state[streamID]
        else:
            state = FilterState()
            self.state[streamID]= state
        
        #cash off these values in case they are configured during this process loop
        aCmplx = self.aCmplx
        bCmplx = self.bCmplx
        a = self._a
        b = self._b
        #check to see if we need to rebuild the filter state
        if state.updateFilter:
            state._applyNewFilterChanges(a, b, aCmplx or bCmplx)
        
        #check to see if we need to push an SRI update
        if sriChanged or state.forceSriUpdate or not self.port_dataFloat_out.sriDict.has_key(streamID):
            self._updateSRI(sri)
        
        #if the input data is complex - unpack it 
        if state.inputCmplx:
            x = self._convertCmplx(data)
        else:    
            x = data

        #here is the actual filter operation courtesy of scipy
        output, zi = lfilter(b,a,x,zi=state.zi)
        
        #update the state for later
        state.lastX = x
        state.lastY = output
        state.zi = zi
        
        #now get ready to send the output
        outData = output.tolist()
        if state.outputCmplx:
            sendCmplx=True
            #check for the condition that we were sending complex but all the complex data is out of the system
            #and we can switch to sending real
            #if any of the state is complex we don't update the filter
            updateFilter = not (state.inputCmplx or aCmplx or bCmplx or self._isCmpxl(zi))
            if updateFilter:
                #state contains no complex data - lets check to see if we have any in the current output

                sendCmplx = self._isCmpxl(outData)              
                #strip off negligible imaginary values to ensure lastY is purely real 
                #so we can reset the filter initial conditions next time
                state.lastY = [x.real for x in outData]
                #set all our flags so we know for next loop to update things
                state.updateFilter=True
                state.forceSriUpdate=True
                state.outputCmplx=False           
            
            #typical steady state complex case - unpack the real & complex parts to send them out
            if sendCmplx:
                unpackedOutdata=[]      
                for val in outData:
                    unpackedOutdata.append(val.real)
                    unpackedOutdata.append(val.imag)
                    outData=unpackedOutdata
            else:              
                #now we are sending out real data
                #we've already stripped off lastY to be just the real - just use it for sending the data
                outData = state.lastY
                
                if (sri.mode!=0):
                    print "freqfilter - ERROR - this shouldn't happen"
                    sri.mode = 0
                #if we are sending out real we must push an sri first to alert down stream of the change  
                self._updateSRI(sri)

        #finally get to push the output
        self.port_dataFloat_out.pushPacket(outData, T, EOS, streamID)
        #if we are done with this stream then pop off the state
        if EOS:
            self.state.pop(streamID)
        return NORMAL

    def configure(self, configProperties):
        """override base class
        """
        #call base class method
        freqfilter_base.configure(self, configProperties)
        #check to see if we need to update our filter props
        for prop in configProperties:
            if prop.id in ("aCmplx", "bCmplx", "a", "b"):
                self._rebuildFilter()
                for state in self.state.values():
                    state.updateFilter = True
                break
  
if __name__ == '__main__':
    logging.getLogger().setLevel(logging.WARN)
    logging.debug("Starting Component")
    start_component(freqfilter_i)
