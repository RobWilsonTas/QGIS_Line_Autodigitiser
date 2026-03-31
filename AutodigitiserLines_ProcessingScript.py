import os, processing
from qgis.core import (QgsProcessingAlgorithm,QgsProcessingParameterRasterLayer,QgsProcessingParameterNumber, QgsProcessing,QgsProject, QgsVectorLayer, QgsLineSymbol,
    QgsSimpleLineSymbolLayer, QgsSingleSymbolRenderer)
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtCore import Qt

class Autodigitiser(QgsProcessingAlgorithm):

    INPUT_RASTER = 'INPUT_RASTER'
    TARGET_RED = 'TARGET_RED'
    TARGET_GREEN = 'TARGET_GREEN'
    TARGET_BLUE = 'TARGET_BLUE'
    SENSITIVITY = 'SENSITIVITY'

    def initAlgorithm(self, config=None):
        
        #Let the user pick the raster to work on
        self.addParameter(QgsProcessingParameterRasterLayer(self.INPUT_RASTER,'Input raster'))
        
        #Let the user pick the red value they want to extract
        self.addParameter(QgsProcessingParameterNumber(self.TARGET_RED,
            'Target red value',type=QgsProcessingParameterNumber.Integer,defaultValue=255))
        
        #Green value to extract
        self.addParameter(QgsProcessingParameterNumber(self.TARGET_GREEN,
            'Target green value',type=QgsProcessingParameterNumber.Integer,defaultValue=0))
        
        #Blue value to extract
        self.addParameter(QgsProcessingParameterNumber(self.TARGET_BLUE,
            'Target blue value',type=QgsProcessingParameterNumber.Integer,defaultValue=0))
        
        #How much wide of a threshold to have around the chosen colour
        self.addParameter(QgsProcessingParameterNumber(self.SENSITIVITY,
            'Sensitivity threshold (start low and increase to see how high you can get it without it bleeding over)',type=QgsProcessingParameterNumber.Integer,defaultValue=10))
        

    def processAlgorithm(self, parameters, context, feedback):
        
        #Grab all of the inputs given
        inputRaster = self.parameterAsRasterLayer(parameters, self.INPUT_RASTER, context)
        targetRed = self.parameterAsInt(parameters, self.TARGET_RED, context)
        targetGreen = self.parameterAsInt(parameters, self.TARGET_GREEN, context)
        targetBlue = self.parameterAsInt(parameters, self.TARGET_BLUE, context)
        sensitivity = self.parameterAsInt(parameters, self.SENSITIVITY, context)
        
        #Figure out the pixel size, will be useful for skeleton thinning etc
        pixelSize = inputRaster.rasterUnitsPerPixelX()
        
        #Where all the output files will go, same folder as input
        folderPath = os.path.dirname(inputRaster.source()) + '/'
        
        """
        ################################################################################################
        Processing
        """
        
        #Build a formula for the raster calculator to pick out only the colour we want
        calcExpression = '(A < ' + str(targetRed + sensitivity) + ') * (A > ' + str(targetRed - sensitivity) + ') * ' + \
                         '(B < ' + str(targetGreen + sensitivity) + ') * (B > ' + str(targetGreen - sensitivity) + ') * ' + \
                         '(C < ' + str(targetBlue + sensitivity) + ') * (C > ' + str(targetBlue - sensitivity) + ')'
                         
        #Run the raster calc: pixels that are within bounds of the chosen colour are set to 1, everything else is 0
        rasterCalc = processing.run("gdal:rastercalculator", {'INPUT_A': inputRaster.source(),'BAND_A':1,'INPUT_B':inputRaster.source(),'BAND_B':2,'INPUT_C':inputRaster.source(),
            'BAND_C':3,'FORMULA':calcExpression,'RTYPE':1,'OUTPUT':QgsProcessing.TEMPORARY_OUTPUT}, context=context, feedback=feedback)['OUTPUT']
        
        #Turn the mask into polygons, so we can work with lines later
        polygonised = processing.run("gdal:polygonize", {'INPUT':rasterCalc,'BAND':1,'FIELD':'DN','OUTPUT':QgsProcessing.TEMPORARY_OUTPUT}, context=context, feedback=feedback)['OUTPUT']
        
        #Keep only the polygons where our colour was actually found
        filtered = processing.run("native:extractbyexpression", {'INPUT':polygonised,'EXPRESSION':'"DN" = 1',
            'OUTPUT':QgsProcessing.TEMPORARY_OUTPUT}, context=context, feedback=feedback)['OUTPUT']
        
        #Buffer out a bit so that the results are a bit smoother
        bufferedLayer = processing.run("native:buffer", {'INPUT':  filtered,'DISTANCE': pixelSize * 3,'SEGMENTS': 3,'END_CAP_STYLE': 0,'JOIN_STYLE': 0,'MITER_LIMIT': 2,
            'DISSOLVE': True,'SEPARATE_DISJOINT': False,'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT}, context=context, feedback=feedback)['OUTPUT']
            
        singlePartLayer = processing.run("native:multiparttosingleparts", {'INPUT': bufferedLayer, 'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT},
            context=context, feedback=feedback)['OUTPUT']

        #Then go back in from the previous buffer
        inBufferedLayer = processing.run("native:buffer", {'INPUT': singlePartLayer,'DISTANCE': pixelSize * -3,'SEGMENTS': 3,'END_CAP_STYLE': 0,'JOIN_STYLE': 0,'MITER_LIMIT': 2,
            'DISSOLVE': True,'SEPARATE_DISJOINT': False,'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT}, context=context, feedback=feedback)['OUTPUT']
            
        cleaned = processing.run("native:deletecolumn", {'INPUT':inBufferedLayer, 'COLUMN': ['fid'], 'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT}, context=context, feedback=feedback)['OUTPUT']
        
        #Make a skeleton of the polygons so we get centre lines (basically marking the centre of the lines)
        skeleton = processing.run("grass:v.voronoi.skeleton", {'input':cleaned,'smoothness':1,'thin':pixelSize * 3,'-s':True,'output':QgsProcessing.TEMPORARY_OUTPUT}, context=context, feedback=feedback)['output']
        
        #Remove any tiny lines, they are probably just noise
        skeletonExtract = processing.run("native:extractbyexpression", {'INPUT':skeleton,'EXPRESSION':'$length > ' + str(pixelSize * 2),'OUTPUT':QgsProcessing.TEMPORARY_OUTPUT},
            context=context, feedback=feedback)['OUTPUT']
        
        #Smooth out the lines a bit
        finalDigitisedLines = processing.run("native:simplifygeometries", {'INPUT':skeletonExtract,'METHOD':0,'TOLERANCE':pixelSize,'OUTPUT':QgsProcessing.TEMPORARY_OUTPUT}, context=context, feedback=feedback)['OUTPUT']  
        
        QgsProject.instance().addMapLayer(finalDigitisedLines)
        
        """
        ################################################################################################
        Styling
        """
        
        #Style it up as a dash so that it can be seen easily
        symbol = QgsLineSymbol()
        l1 = QgsSimpleLineSymbolLayer(QColor(0,0,0),0.66,Qt.SolidLine)
        l1.setUseCustomDashPattern(True)
        l1.setCustomDashVector([5,2])
        symbol.appendSymbolLayer(l1)
        l2 = QgsSimpleLineSymbolLayer(QColor(255,255,255),0.46,Qt.DotLine)
        l2.setUseCustomDashPattern(True)
        l2.setCustomDashVector([5,2])
        symbol.appendSymbolLayer(l2)
        symbol.deleteSymbolLayer(0)
        finalDigitisedLines.setRenderer(QgsSingleSymbolRenderer(symbol))
        finalDigitisedLines.triggerRepaint()
        
        #Return nothing because you have to return something
        return {}
        
    """
    ################################################################################################
    Final definitions of names etc
    """

    def name(self):
        return 'autodigitiser'

    def displayName(self):
        return 'Autodigitiser'

    def group(self):
        return 'Custom Scripts'

    def groupId(self):
        return 'customscripts'

    def createInstance(self):
        return Autodigitiser()
