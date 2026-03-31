import os, processing
from qgis.core import (QgsProcessingAlgorithm,QgsProcessingParameterRasterLayer,QgsProcessingParameterNumber, QgsProcessing,QgsProject, QgsVectorLayer)
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtCore import Qt

class AutodigitiserPolygons(QgsProcessingAlgorithm):

    # Define the parameters the user will set
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
        try:
            
            #Grab user inputs
            inputRaster = self.parameterAsRasterLayer(parameters, self.INPUT_RASTER, context)
            targetRed = self.parameterAsInt(parameters, self.TARGET_RED, context)
            targetGreen = self.parameterAsInt(parameters, self.TARGET_GREEN, context)
            targetBlue = self.parameterAsInt(parameters, self.TARGET_BLUE, context)
            sensitivity = self.parameterAsInt(parameters, self.SENSITIVITY, context)

            #Pixel size in map units
            pixelSize = inputRaster.rasterUnitsPerPixelX()
            folderPath = os.path.dirname(inputRaster.source()) + '/'
            
            """
            ##################################################################################################################
            Actual processing
            """

            #Build a formula for the raster calculator to pick out only the colour we want
            calcExpression = '(A < ' + str(targetRed + sensitivity) + ') * (A > ' + str(targetRed - sensitivity) + ') * ' + \
                             '(B < ' + str(targetGreen + sensitivity) + ') * (B > ' + str(targetGreen - sensitivity) + ') * ' + \
                             '(C < ' + str(targetBlue + sensitivity) + ') * (C > ' + str(targetBlue - sensitivity) + ')'
            
            #Run the raster calc: pixels that are within bounds of the chosen colour are set to 1, everything else is 0
            rasterCalc = processing.run("gdal:rastercalculator", {'INPUT_A': inputRaster.source(),'BAND_A':1,
                'INPUT_B':inputRaster.source(),'BAND_B':2, 'INPUT_C':inputRaster.source(),'BAND_C':3,
                'FORMULA':calcExpression,'RTYPE':1,'OUTPUT':QgsProcessing.TEMPORARY_OUTPUT}, context=context, feedback=feedback)['OUTPUT']

            #Turn those pixels into polygons
            polygonised = processing.run("gdal:polygonize", {'INPUT':rasterCalc,'BAND':1,'FIELD':'DN','OUTPUT':QgsProcessing.TEMPORARY_OUTPUT}, context=context, feedback=feedback)['OUTPUT']

            #Keep only polygons where the colour was found
            filtered = processing.run("native:extractbyexpression", {'INPUT':polygonised,'EXPRESSION':'"DN" = 1','OUTPUT':QgsProcessing.TEMPORARY_OUTPUT}, context=context, feedback=feedback)['OUTPUT']

            #Add a tiny buffer to clean up edges
            bufferedLayer = processing.run("native:buffer", {'INPUT': filtered,'DISTANCE': pixelSize * 2,'SEGMENTS': 3,
                'END_CAP_STYLE': 0,'JOIN_STYLE': 0,'MITER_LIMIT': 2,'DISSOLVE': True,'SEPARATE_DISJOINT': False,
                'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT}, context=context, feedback=feedback)['OUTPUT']
                
            #Reverse to not extend too far
            inBufferedLayer = processing.run("native:buffer", {'INPUT':bufferedLayer,'DISTANCE': pixelSize * -1,'SEGMENTS': 3,
                'END_CAP_STYLE': 0,'JOIN_STYLE': 0,'MITER_LIMIT': 2,'DISSOLVE': True,'SEPARATE_DISJOINT': False,
                'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT}, context=context, feedback=feedback)['OUTPUT']

            #Split any multi-part polygons into single parts
            singlePartLayer = processing.run("native:multiparttosingleparts", {'INPUT':inBufferedLayer,'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT}, context=context, feedback=feedback)['OUTPUT']
            
            #Smooth out the lines
            simplifiedPolygons = processing.run("native:simplifygeometries", {'INPUT':singlePartLayer,'METHOD':0,'TOLERANCE':pixelSize * 1,'OUTPUT':QgsProcessing.TEMPORARY_OUTPUT}, context=context, feedback=feedback)['OUTPUT']

            #Fix up broken geom
            fixedGeometries = processing.run("native:fixgeometries", {'INPUT':simplifiedPolygons,'METHOD':1,'OUTPUT':QgsProcessing.TEMPORARY_OUTPUT}, context=context, feedback=feedback)['OUTPUT']

            #Add final polygons to the map
            QgsProject.instance().addMapLayer(fixedGeometries)

            """
            ##################################################################################################################
            Final stuff
            """

            return {}

        except BaseException as e:
            #Something went wrong, tell the user
            feedback.raiseError(str(e))

    # Script metadata
    def name(self):
        return 'autodigitiser_polygons'

    def displayName(self):
        return 'Autodigitiser (Polygons)'

    def group(self):
        return 'NB Custom Scripts'

    def groupId(self):
        return 'nbcustomscripts'

    def createInstance(self):
        return AutodigitiserPolygons()