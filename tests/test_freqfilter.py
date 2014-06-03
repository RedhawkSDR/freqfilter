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
import unittest
import ossie.utils.testing
from ossie.utils import sb
import os
from omniORB import any, orb
import time
from ossie.cf import CF
from omniORB import CORBA
import math
from scipy.signal import iirdesign, remez, correlate, tf2zpk
from scipy.fftpack import fft, rfft
from numpy import log10
import operator
import random
import sys
sys.path.append('../../fastfilter/tests')

from test_fastfilter import ImpulseResponseMixIn
#The IIR design techniques are not as good - have more grace 
#for doing the validation here
ImpulseResponseMixIn.RIPPLE_MULT=2.0

def toCx(input):
    cx=[]
    for i in xrange(len(input)/2):
        cx.append(complex(input[2*i],input[2*i+1]))
    return cx

def toReal(input):
    re=[]
    for val in input:
        re.append(val.real)
        re.append(val.imag)
    return re

def muxZeros(input):
    out = []
    for val in input:
        out.append(complex(val,0.0))
    return out

class ComponentTests(ossie.utils.testing.ScaComponentTestCase, ImpulseResponseMixIn):
    """Test for all component implementations in fcalc"""
    
    #make some random taps but lets make sure we are stable
    while True:
        B = [random.random() for _ in xrange(10)]
        A = [random.random() for _ in xrange(6)]
        poles = tf2zpk(B,A)[1]
        if all([abs(x)<1 for x in poles]):
            break
    
    while True:        
        B_CX = [complex(random.random(),random.random()) for _ in xrange(10)]
        A_CX = [complex(random.random(),random.random()) for _ in xrange(6)]
        poles = tf2zpk(B_CX,A_CX)[1]
        if all([abs(x)<1 for x in poles]):
            break

            
    INPUT = [random.random() for _ in xrange(1024)]
        
    REALOUT = None
    CXOUT = None

    #utility methods to help with SCA set up and tear down for testing

    def _getCfFloatSeq(self, inData):
        data=[]
        for x in inData:
            if isinstance(x,complex):
                data.append(ossie.cf.CF.complexFloat(real=x.real, imag=x.imag))
            else:
                data.append(ossie.cf.CF.complexFloat(real=x, imag=0.0))
        return CORBA.Any(orb.create_sequence_tc(bound=0, element_type=CORBA.TypeCode("IDL:CF/complexFloat:1.0")), data)        

    def setProps(self, a=None,b=None,filterProps=None):
        myProps=[]
        
        if a!=None:
            self.a = a
            myProps.append(CF.DataType(id='a', value=self._getCfFloatSeq(a)))
        
        if b!=None:
            self.b = b
            myProps.append(CF.DataType(id='b', value=self._getCfFloatSeq(b)))
        
        if filterProps!=None:
            myProps.append(self.makeFilterProps(**filterProps))
        
        if myProps:
            self.comp.configure(myProps)

    def setUp(self):
        """Set up the unit test - this is run before every method that starts with test
        """
        ossie.utils.testing.ScaComponentTestCase.setUp(self)
        self.src = sb.DataSource()
        self.sink = sb.DataSink()
        
        #setup my components
        self.setupComponent()
        
        self.comp.start()
        self.src.start()
        self.sink.start()
        
        #do the connections
        self.src.connect(self.comp)        
        self.comp.connect(self.sink,'floatIn')
        self.output=[]
        
    def tearDown(self):
        """Finish the unit test - this is run after every method that starts with test
        """
        self.comp.stop()
        #######################################################################
        # Simulate regular component shutdown
        self.comp.releaseObject()
        self.sink.stop()      
        ossie.utils.testing.ScaComponentTestCase.tearDown(self)

    def setupComponent(self):
        """Standard start-up for testing the component
        """
        #######################################################################
        # Launch the component with the default execparams
        execparams = self.getPropertySet(kinds=("execparam",), modes=("readwrite", "writeonly"), includeNil=False)
        execparams = dict([(x.id, any.from_any(x.value)) for x in execparams])
        self.launch(execparams, initialize=True)
        
        #######################################################################
        # Verify the basic state of the component
        self.assertNotEqual(self.comp, None)
        self.assertEqual(self.comp.ref._non_existent(), False)
        self.assertEqual(self.comp.ref._is_a("IDL:CF/Resource:1.0"), True)
        #self.assertEqual(self.spd.get_id(), self.comp.ref._get_identifier())
        
        #######################################################################
        # Simulate regular component startup
        # Verify that initialize nor configure throw errors
        #self.comp.initialize()
        configureProps = self.getPropertySet(kinds=("configure",), modes=("readwrite", "writeonly"), includeNil=False)
        self.comp.configure(configureProps)
        
        #######################################################################
        # Validate that query returns all expected parameters
        # Query of '[]' should return the following set of properties
        expectedProps = []
        expectedProps.extend(self.getPropertySet(kinds=("configure", "execparam"), modes=("readwrite", "readonly"), includeNil=True))
        expectedProps.extend(self.getPropertySet(kinds=("allocate",), action="external", includeNil=True))
        props = self.comp.query([])
        props = dict((x.id, any.from_any(x.value)) for x in props)
        # Query may return more than expected, but not less
        for expectedProp in expectedProps:
            self.assertEquals(props.has_key(expectedProp.id), True)
        
        #######################################################################
        # Verify that all expected ports are available
        for port in self.scd.get_componentfeatures().get_ports().get_uses():
            port_obj = self.comp.getPort(str(port.get_usesname()))
            self.assertNotEqual(port_obj, None)
            self.assertEqual(port_obj._non_existent(), False)
            self.assertEqual(port_obj._is_a("IDL:CF/Port:1.0"),  True)
            
        for port in self.scd.get_componentfeatures().get_ports().get_provides():
            port_obj = self.comp.getPort(str(port.get_providesname()))
            self.assertNotEqual(port_obj, None)
            self.assertEqual(port_obj._non_existent(), False)
            self.assertEqual(port_obj._is_a(port.get_repid()),  True)

    def designIIR(self):
        """Design an iir filter with a passband from .3 to .35 using iirdesign from scipy
        """
        #note - the default filter returned with the default ftype for these
        #parameters was UNSTABLE leading to random unit test failures with nans 
        #cheby2 returns a stable filter
        b, a = iirdesign([.3, .35], [.1, .5],.1,20, ftype='cheby2')
        return b.tolist(), a.tolist()
    
    def designFIR(self):
        """Design a fir filter with a passband from .3 to .35 using remez from scipy
        """
        taps =  remez(64,[0,.1,.3,.35,.5,1.0],[.01,1,.01],Hz=2)
        return taps.tolist()  

    def testBadCfg(self):
        """Set with multiple filterProp settings simultaniously and verify we get an error
        """
        try:
            self.setProps(self.A,self.B,{})
        except CF.PropertySet.InvalidConfiguration:
            return
        raise RunTimeError("No error raised in testBadCfg1")

    def testNoCfg(self):
        """Validate component doesn't fail miserably without any configuration
        """
        self.main([self.INPUT])
    
    #the first four tests are designed to work in pairs
    #make random taps & input data and send it all through
    #then send half through and the second half through again
    #ensure the two outputs are the same
    #mainly this is to help test the filter state tracking stuff is working appropriately
    def testAllReal(self):
        """Real test part 1
        """
        self.setProps(self.A,self.B)
        self.main([self.INPUT])
        if ComponentTests.REALOUT ==None:
            ComponentTests.REALOUT = self.output
        else:
            self.assertTrue(ComponentTests.REALOUT==self.output)
    
    def testHalfReal(self):    
        """real test part 2
        """
        self.setProps(self.A,self.B)
        numPush = len(self.INPUT)/2
        self.main([self.INPUT[:numPush]])
        self.main([self.INPUT[numPush:]])
        if ComponentTests.REALOUT ==None:
            ComponentTests.REALOUT = self.output
        else:
            self.assertTrue(ComponentTests.REALOUT==self.output)

    def testAllCx(self):
        """Cx test part 1
        """
        
        self.setProps(self.A_CX,self.B_CX)
        self.main([self.INPUT])
        if ComponentTests.CXOUT ==None:
            ComponentTests.CXOUT = self.output
        else:
            self.assertTrue(ComponentTests.CXOUT==self.output)
    
    def testHalfCx(self):    
        """cx test part 2
        """
        self.setProps(self.A_CX,self.B_CX)
        numPush = len(self.INPUT)/2
        self.main([self.INPUT[:numPush]])
        self.main([self.INPUT[numPush:]])
        if ComponentTests.CXOUT ==None:
            ComponentTests.CXOUT = self.output
        else:
            self.assertTrue(ComponentTests.CXOUT==self.output)
    
    def testAllRealDefaultConfig(self):
        """Real test part 1 with default config (No Filtering)
        """
        self.main([self.INPUT])
        if ComponentTests.REALOUT ==None:
            ComponentTests.REALOUT = self.output
        else:
            a = self.INPUT
            b = self.output
            tolerance = 0.01
            diffs = map(lambda a,b:a-b,a,b)
            # Check that every value is within the tolerance
            for diff in diffs:
              self.assertTrue(diff < tolerance)
    
    def testImpulseIIROneAtATime(self):
        """send in one input at a time to make sure that the filter is doing its state updates properly
           Not very efficient filtering but a good test case
        """
        b, a= self.designIIR()
        self.impluseResponseTest(a,b,False)

    def testImpulseIIROneAtATimeNoCfg(self):
        """send in one input at a time to make sure that the filter is doing its state updates properly
           Not very efficient filtering but a good test case
        """
        b, a= self.designIIR()
        self.setProps(a,b)
        self.impulseResponseNoCfg(False) 
 
            
    def testImpluseIIR(self):
        """IIR Test 1
        """
        b, a= self.designIIR()
        self.impluseResponseTest(a,b)
    
    def testSinIIR(self):
        """IIR Test 2
        """
        b, a= self.designIIR()
        self.sinInputTest(a,b)
    
    def testImpulseFIR(self):
        """FIR test 1
        """
        taps = self.designFIR()
        self.impluseResponseTest([1],taps)
    
    def testSinFIR(self):
        """FIR TEST 2
        """
        taps = self.designFIR()
        self.sinInputTest([1],taps)
    
    def testCxImpulseResponse(self):
        """TEST 1 with complex data
        """
        b, a= self.designIIR()
        self.impluseResponseTest(a,b,dataCx=True)
    
    def testCxSin(self):
        """Test 2 with complex data
        """
        b, a= self.designIIR()
        self.sinInputTest(a,b,dataCx = True)
    
    def testRealToComplex(self):
        """Test 2 -- Send real data through - then send complex
           Ensure output is first real but then complex
        """
        b, a= self.designIIR()
        self.sinInputTest(a,b)
        self.assertFalse(self.outputCmplx)
        self.output=[]
        self.sinInputTest(a,b,dataCx=True)
        self.assertTrue(self.outputCmplx)

    def testComplexToReal(self):
        """Test 2 -- Send complex data through - then send real
           Ensure output is first complex but then finally real
        """
        b, a= self.designIIR()
        self.sinInputTest(a,b,dataCx=True)
        self.assertTrue(self.outputCmplx)
        self.output=[]
        self.sinInputTest(a,b,dataCx=False)
        self.output=[]
        #need to send real data through one more time to get real output
        #as there are residual complex effects in the filter as expected
        self.sinInputTest(a,b,dataCx=False)
        self.assertFalse(self.outputCmplx)

    def testEOS(self):
        dataCx=False
        b, a= self.designIIR()
        t1 = self.setProps(a,b)
                #in the pass band
        s1 = self.genSinWave(.325,1024,dataCx=dataCx)
        #these next two are in the stop bands
        s2 = self.genSinWave(.75,1024,dataCx=dataCx)
        s3 = self.genSinWave(.05,1024,dataCx=dataCx)
        input = [x+y+z for x,y,z in zip(s1,s2,s3)]
        trans = self.getTransient(input)
        
        #we are already in steady state mode
        steadyState = self.getTransient(input, eos=True)
        trans2  = self.getTransient(input, eos=True)
        self.assertTrue(trans==trans2)
        self.assertTrue(trans!=steadyState)
    
    def testMultiStream(self):
        b, a= self.designIIR()
        self.setProps(a,b)
                 
        #give us a bit of time to make sure the configure finishes up
        self.impulseResponseNoCfg(streamID = "firstStream")
        self.impulseResponseNoCfg(streamID = "secondStream")

    def getTransient(self,inData, dataCx=False, eos=False):
        """Make a test with three different sinusoidal inputs --
           One in the passband and two in the stopbands 
           The response should be equal to the sinusoid in the passband
           With a caveat - the frequency domain 
        """
        
        self.main([inData],dataCx=dataCx, eos=eos)

        #Kind of a bit of a lame validation here
        #Filtering may introduce a phase offset at our frequency of interest
        #So - we may end up with a delayed version of the two sine waves
        #which is not an integer multiple
        #this makes it more difficult to do the validation between s1 and the output
        #as such - I'm doing my validation in the frequency domain and taking the abs
        #to discount any phase ambiguities
        
        #I'm also removing the first points as there could be weird transients with the output

        transientNum=60
        out = self.output[:transientNum]
        self.output=[]
        return out

              
    def impluseResponseTest(self,a,b,sendAll=True,dataCx=False):
        """ Run an impulse into the filter and test the impulse response
            Just take the fft and work with it to get an idea of the frequency response
        """
        self.setProps(a,b)
        self.impulseResponseNoCfg(sendAll,dataCx)
        
    def impulseResponseNoCfg(self, sendAll=True,dataCx=False, streamID="myStream"):
        input = [1.0]
        input.extend([0]*1023) 
        if sendAll:
            self.main([input],dataCx, streamID=streamID)
        else:
            for x in input:
                self.src.push([x],complexData=dataCx, streamID=streamID)
            self.main(streamID=streamID)
        
        #take the 20 log fft of the abs of the response
        f = fft(self.output,1024).tolist()
        m = [20*log10(abs(x)) for x in f]
        
        freqDelta = 2.0/1024
        #check the passband
        startIndex = int(.3/freqDelta)
        stopIndex = int(.35/freqDelta)
                
        passBand = m[startIndex:stopIndex]
        self.assertTrue((max(passBand)-min(passBand))<1)
        
        #check the two stop bands
        stopIndex1 = int(.1/freqDelta)
        stopBand1 = m[:stopIndex1]
        self.assertTrue((max(stopBand1))<-20)
        
        stopIndex1 = int(.5/freqDelta)
        stopIndex2 = int(1.0/freqDelta)
        stopBand2 = m[stopIndex1:stopIndex2]
        self.assertTrue((max(stopBand2))<-20)
    
    def sinInputTest(self,a,b,dataCx=False):
        """Make a test with three different sinusoidal inputs --
           One in the passband and two in the stopbands 
           The response should be equal to the sinusoid in the passband
           With a caveat - the frequency domain 
        """
        self.setProps(a,b)
        
        #in the pass band
        s1 = self.genSinWave(.325,1024,dataCx=dataCx)
        #these next two are in the stop bands
        s2 = self.genSinWave(.75,1024,dataCx=dataCx)
        s3 = self.genSinWave(.05,1024,dataCx=dataCx)
        input = [x+y+z for x,y,z in zip(s1,s2,s3)]
        
        self.main([input],dataCx=dataCx)

        #Kind of a bit of a lame validation here here 
        #Filtering may introduce a phase offset at our frequency of interest
        #So - we may end up with a delayed version of the two sin waves
        #which is not an integer multiple
        #this makes it more difficult to do the validation between s1 and the output
        #as such - I'm doing my validation in the frequency domain and taking the abs
        #to discount any phase ambiguities
        
        #I'm also removing the first points as there could be weird transients with the output

        transientNum=60
        fftSize=512
        if dataCx:
            #need to convert s1 to be actual complex values to complete the analysis
            cx = toCx(s1)
            fS1 = fft(cx[transientNum:],fftSize).tolist()
        else:
            fS1 = fft(s1[transientNum:],fftSize).tolist()
        
        fOut = fft(self.output[transientNum:],fftSize).tolist()      
        d = [abs(abs(x)-abs(y)) for (x,y) in zip(fOut,fS1)]
        meanError = sum(d)/len(d)
        self.assertTrue(meanError< .5)

    def genSinWave(self, freq,NumPts,fs=2.0,dataCx=False):
        f = freq/fs
        if dataCx:
            out=[]
            for i in xrange(NumPts):
                phase = 2*math.pi*f*i
                out.append(math.cos(phase))
                out.append(math.sin(phase))
            return out
        else:
            return [math.sin(2*math.pi*f*i) for i in xrange(NumPts)]
            
    def validateSRIPushing(self, sampleRate=1.0, streamID='test_stream'):
        self.assertEqual(self.sink.sri().streamID, streamID, "Component not pushing streamID properly")
        # Account for rounding error
        calcSR = 1/self.sink.sri().xdelta
        diffSR = abs(calcSR-sampleRate)
        tolerance = 1
        self.assertTrue(diffSR < tolerance, "Component not pushing samplerate properly")

    def main(self,inData=[], dataCx=False,eos=False, streamID="test_stream", sampleRate=1.0):
        """The main engine for all the test cases - configure the equation, push data, and get output
           As applicable
        """
        #data processing is asynchronos - so wait until the data is all processed
        count=0
        thisOutput=[]
        if inData:
            #just to mix things up I'm going to push through in two stages
            #to ensure the filter is working properly with its state
            
            for data in inData:
                self.src.push(data,complexData=dataCx, EOS=eos, streamID=streamID,sampleRate=sampleRate)
        while True:
            newOut = self.sink.getData()
            if newOut:
                thisOutput.extend(newOut)
                count=0
            if count==50:
                break
            time.sleep(.01)
            count+=1
        #convert the output to complex if necessary    
        self.outputCmplx = self.sink.sri().mode==1
        if self.outputCmplx:
            thisOutput = toCx(thisOutput)
        self.output.extend(thisOutput)
    
if __name__ == "__main__":
    ossie.utils.testing.main("../freqfilter.spd.xml") # By default tests all implementations
