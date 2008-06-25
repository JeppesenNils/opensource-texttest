import os, performance, filecmp, string, plugins, shutil
from ndict import seqdict
from tempfile import mktemp
from comparefile import FileComparison
from sets import Set

plugins.addCategory("success", "succeeded")
plugins.addCategory("failure", "FAILED")

class BaseTestComparison(plugins.TestState):
    def __init__(self, category, previousInfo, completed, lifecycleChange=""):
        plugins.TestState.__init__(self, category, "", started=1, completed=completed, \
                                   lifecycleChange=lifecycleChange, executionHosts=previousInfo.executionHosts)
        self.allResults = []
        self.changedResults = []
        self.newResults = []
        self.missingResults = []
        self.correctResults = []
        self.diag = plugins.getDiagnostics("TestComparison")

    def hasResults(self):
        return len(self.allResults) > 0
    def isAllNew(self):
        return len(self.newResults) == len(self.allResults)
    
    def computeFor(self, test):
        self.makeComparisons(test)
        self.categorise()
        test.changeState(self)
    def fakeMissingFileText(self):
        return "Auto-generated by TextTest to simulate missing file for this version...\n"
    def shouldCompare(self, resultFile):
        firstLine = open(resultFile).readline()
        return firstLine != self.fakeMissingFileText()
    def makeComparisons(self, test):
        # Might have saved some new ones or removed some old ones in the meantime...
        test.refreshFiles()
        tmpFiles = self.makeStemDict(test.listTmpFiles())
        resultFiles, defFiles = test.listStandardFiles(allVersions=False)
        resultFilesToCompare = filter(self.shouldCompare, resultFiles)
        stdFiles = self.makeStemDict(resultFilesToCompare + defFiles)
        for tmpStem, tmpFile in tmpFiles.items():
            self.notifyIfMainThread("ActionProgress", "")
            stdFile = stdFiles.get(tmpStem)
            self.diag.info("Comparing " + repr(stdFile) + "\nwith " + tmpFile) 
            comparison = self.createFileComparison(test, tmpStem, stdFile, tmpFile)
            if comparison:
                self.addComparison(comparison)
        self.makeMissingComparisons(test, stdFiles, tmpFiles, defFiles)
    def makeMissingComparisons(self, test, stdFiles, tmpFiles, defFiles):
        pass

    def addComparison(self, comparison):
        info = "Making comparison for " + comparison.stem + " "
        if comparison.isDefunct():
            # typically "missing file" that got "saved" and removed
            info += "(defunct)"
        else:
            self.allResults.append(comparison)
            if comparison.newResult():
                self.newResults.append(comparison)
                info += "(new)"
            elif comparison.missingResult():
                self.missingResults.append(comparison)
                info += "(missing)"
            elif comparison.hasDifferences():
                self.changedResults.append(comparison)
                info += "(diff)"
            else:
                self.correctResults.append(comparison)
                info += "(correct)"
        self.diag.info(info)

    def makeStemDict(self, files):
        stemDict = seqdict()
        for file in files:
            stem = os.path.basename(file).split(".")[0]
            stemDict[stem] = file
        return stemDict

        
class TestComparison(BaseTestComparison):
    def __init__(self, previousInfo, app, lifecycleChange=""):
        BaseTestComparison.__init__(self, "failure", previousInfo, completed=1, lifecycleChange=lifecycleChange)
        self.failedPrediction = None
        if previousInfo.category == "killed":
            self.setFailedPrediction(previousInfo)
        if hasattr(previousInfo, "failedPrediction") and previousInfo.failedPrediction:
            self.setFailedPrediction(previousInfo.failedPrediction)
        # Cache these only so it gets output when we pickle, so we can re-interpret if needed... data may be moved
        self.appAbsPath = app.getDirectory()
        self.appWriteDir = app.writeDirectory
    def categoryRepr(self):    
        if self.failedPrediction:
            briefDescription, longDescription = self.categoryDescriptions[self.category]
            return longDescription + " (" + self.failedPrediction.briefText + ")"
        else:
            return plugins.TestState.categoryRepr(self)
    def __getstate__(self):
        # don't pickle the diagnostics
        state = {}
        for var, value in self.__dict__.items():
            if var != "diag":
                state[var] = value
        return state

    def __setstate__(self, state):
        self.__dict__ = state
        self.diag = plugins.getDiagnostics("TestComparison")
        # If loaded from old pickle files, can get out of date objects...
        if not hasattr(self, "missingResults"):
            self.missingResults = []

    def updateAbsPath(self, newPath):
        if self.appAbsPath != newPath:
            self.diag.info("Updating abspath " + self.appAbsPath + " to " + newPath)
            for comparison in self.allResults:
                comparison.updatePaths(self.appAbsPath, newPath)
            self.appAbsPath = newPath

    def updateTmpPath(self, newPath):
        if self.appWriteDir != newPath:
            self.diag.info("Updating abspath " + self.appWriteDir + " to " + newPath)
            for comparison in self.allResults:
                comparison.updatePaths(self.appWriteDir, newPath)
            self.appWriteDir = newPath

    def setFailedPrediction(self, prediction):
        self.diag.info("Setting failed prediction to " + str(prediction))
        self.failedPrediction = prediction
        self.freeText = str(prediction)
        self.briefText = prediction.briefText
        self.category = prediction.category
    def hasSucceeded(self):
        return self.category == "success"
    def warnOnSave(self):
        return bool(self.failedPrediction)
    def getComparisonsForRecalculation(self):
        comparisons = []
        for comparison in self.allResults:
            self.diag.info(comparison.stem + " dates " + comparison.modifiedDates())
            if comparison.needsRecalculation():
                self.diag.info("Recalculation needed for file " + comparison.stem)
                comparisons.append(comparison)
        self.diag.info("All file comparisons up to date")
        return comparisons
    def getMostSevereFileComparison(self):
        worstSeverity = None
        worstResult = None
        for result in self.getComparisons():
            severity = result.severity
            if not worstSeverity or severity < worstSeverity:
                worstSeverity = severity
                worstResult = result
        return worstResult
    def getTypeBreakdown(self):
        if self.hasSucceeded():
            return self.category, ""
        if self.failedPrediction:
            return self.failedPrediction.getTypeBreakdown()

        worstResult = self.getMostSevereFileComparison()
        worstSeverity = worstResult.severity
        self.diag.info("Severity " + str(worstSeverity) + " for failing test")
        details = worstResult.getSummary()
        if len(self.getComparisons()) > 1:
            details += "(+)"
        if worstSeverity == 1:
            return "failure", details
        else:
            return "success", details
    def getComparisons(self):
        return self.changedResults + self.newResults + self.missingResults    
    def _comparisonsString(self, comparisons):
        return string.join([repr(x) for x in comparisons], ",")
    # Sort according to failure_display_priority. Lower means show earlier,
    # files with the same prio should be not be shuffled. 
    def getSortedComparisons(self):
        return sorted(self.changedResults, self.lessDisplayPriority) + \
               sorted(self.newResults, self.lessDisplayPriority) + \
               sorted(self.missingResults, self.lessDisplayPriority)
    def lessDisplayPriority(self, first, second):
        if first.displayPriority == second.displayPriority:
            return cmp(first.stem, second.stem)
        else:
            return cmp(first.displayPriority, second.displayPriority)
    def description(self):
        return repr(self) + self.getDifferenceSummary()
    def getDifferenceSummary(self):
        texts = []
        if len(self.newResults) > 0:
            texts.append("new results in " + self._comparisonsString(self.newResults))
        if len(self.missingResults) > 0:
            texts.append("missing results for " + self._comparisonsString(self.missingResults))
        if len(self.changedResults) > 0:
            texts.append("differences in " + self._comparisonsString(self.changedResults))
        if len(texts) > 0:
            return " " + string.join(texts, ", ")
        else:
            return ""
    def getPostText(self):
        if not self.hasResults():
            return " - NONE!"
        if len(self.getComparisons()) == 0:
            return " - SUCCESS! (on " + self.attemptedComparisonsOutput() + ")"
        return " (on " + self.attemptedComparisonsOutput() + ")"
    def attemptedComparisonsOutput(self):
        baseNames = []
        for comparison in self.allResults:
            if comparison.newResult():
                baseNames.append(os.path.basename(comparison.tmpFile))
            else:
                baseNames.append(os.path.basename(comparison.stdFile))
        return string.join(baseNames, ",")
    def makeMissingComparisons(self, test, stdFiles, tmpFiles, defFiles):
        for stdStem, stdFile in stdFiles.items():
            self.notifyIfMainThread("ActionProgress", "")
            if not tmpFiles.has_key(stdStem) and not stdFile in defFiles:
                comparison = self.createFileComparison(test, stdStem, stdFile, None)
                if comparison:
                    self.addComparison(comparison)
    def getPerformanceStems(self, test):
        return [ "performance" ] + test.getConfigValue("performance_logfile_extractor").keys()
    def createFileComparison(self, test, stem, standardFile, tmpFile):
        if stem in self.getPerformanceStems(test):
            if tmpFile:
                return performance.PerformanceFileComparison(test, stem, standardFile, tmpFile)
            else:
                # Don't care if performance is missing
                return None
        else:
            return FileComparison(test, stem, standardFile, tmpFile, testInProgress=0, observers=self.observers)
    def categorise(self):
        if self.failedPrediction:
            # Keep the category we had before
            self.freeText += self.getFreeTextInfo()
            return
        worstResult = self.getMostSevereFileComparison()
        if not worstResult:
            self.category = "success"
        else:
            self.category = worstResult.getType()
            self.freeText = self.getFreeTextInfo()
    def getFreeTextInfo(self):
        texts = [ fileComp.getFreeText() for fileComp in self.getSortedComparisons() ] 
        return string.join(texts, "")
    def findComparison(self, stem, includeSuccess=False):
        lists = [ self.changedResults, self.newResults, self.missingResults ]
        if includeSuccess:
            lists.append(self.correctResults)
        self.diag.info("Finding comparison for stem " + stem)
        for list in lists:
            for comparison in list:
                if comparison.stem == stem:
                    return comparison, list
        return None, None
    def removeComparison(self,stem):
        comparison, newList = self.findComparison(stem)
        newList.remove(comparison)
        self.allResults.remove(comparison)
    def save(self, test, exact=True, versionString="", overwriteSuccessFiles=False, newFilesAsDiags=False, onlyStems=[]):
        self.diag.info("Saving " + repr(test) + " stems " + repr(onlyStems))
        for comparison in self.filterComparisons(self.changedResults, onlyStems):
            self.updateStatus(test, str(comparison), versionString)
            comparison.overwrite(test, exact, versionString)
        for comparison in self.filterComparisons(self.newResults, onlyStems):
            self.updateStatus(test, str(comparison), versionString)
            comparison.saveNew(test, versionString, newFilesAsDiags)
        for comparison in self.filterComparisons(self.missingResults, onlyStems):
            self.updateStatus(test, str(comparison), versionString)
            comparison.saveMissing(versionString, self.fakeMissingFileText())
        # Save any external file edits we may have made
        tmpFileEditDir = test.makeTmpFileName("file_edits", forComparison=0)
        if os.path.isdir(tmpFileEditDir):
            for root, dirs, files in os.walk(tmpFileEditDir):
                for file in sorted(files):
                    fullPath = os.path.join(root, file)
                    savePath = fullPath.replace(test.writeDirectory, test.getDirectory())
                    self.updateStatus(test, "edited file " + file, versionString)
                    plugins.ensureDirExistsForFile(savePath)
                    shutil.copyfile(fullPath, savePath)
        if overwriteSuccessFiles:
            for comparison in self.filterComparisons(self.correctResults, onlyStems):
                self.updateStatus(test, str(comparison), versionString)
                comparison.overwrite(test, exact, versionString)
    def recalculateComparisons(self, test):
        test.refreshFiles()
        resultFiles, defFiles = test.listStandardFiles(allVersions=False)
        stdFiles = self.makeStemDict(resultFiles + defFiles)
        for fileComp in self.allResults:
            stdFile = stdFiles.get(fileComp.stem)
            fileComp.recompute(test, stdFile)
        return True
    def filterComparisons(self, resultList, onlyStems):
        if len(onlyStems) == 0:
            return resultList
        else:
            return filter(lambda comp: comp.stem in onlyStems, resultList)
    def updateStatus(self, test, compStr, versionString):
        testRepr = "Saving " + repr(test) + " : "
        if versionString != "":
            versionRepr = ", version " + versionString
        else:
            versionRepr = ", no version"
        self.notifyIfMainThread("Status", testRepr + compStr + versionRepr)
        self.notifyIfMainThread("ActionProgress", "")
    def makeNewState(self, app, lifeCycleDest):
        newState = TestComparison(self, app, "be " + lifeCycleDest)
        for comparison in self.allResults:
            newState.addComparison(comparison)
        newState.categorise()
        return newState

# for back-compatibility, preserve old names
performance.PerformanceTestComparison = TestComparison

class ProgressTestComparison(BaseTestComparison):
    def __init__(self, previousInfo):
        BaseTestComparison.__init__(self, previousInfo.category, previousInfo, completed=0, lifecycleChange="be recalculated")
        if isinstance(previousInfo, ProgressTestComparison):
            self.runningState = previousInfo.runningState
        else:
            self.runningState = previousInfo
    def processCompleted(self):
        return self.runningState.processCompleted()
    def killProcess(self):
        self.runningState.killProcess()
    def createFileComparison(self, test, stem, standardFile, tmpFile):
        return FileComparison(test, stem, standardFile, tmpFile, testInProgress=1, observers=self.observers)
    def categorise(self):
        self.briefText = self.runningState.briefText
        self.freeText = self.runningState.freeText + self.progressText()
    def progressText(self):
        perc = self.calculatePercentage()
        if perc is not None:
            return "\nReckoned to be " + str(perc) + "% complete at " + plugins.localtime() + "."
        else:
            return ""
    def getSize(self, fileName):
        if fileName and os.path.isfile(fileName):
            return os.path.getsize(fileName)
        else:
            return 0
    def calculatePercentage(self):
        stdSize, tmpSize = 0, 0
        for comparison in self.changedResults + self.correctResults:
            stdSize += self.getSize(comparison.stdFile)
            tmpSize += self.getSize(comparison.tmpFile)

        if stdSize > 0:
            return (tmpSize * 100) / stdSize 

class MakeComparisons(plugins.Action):
    def __init__(self, testComparisonClass=None, progressComparisonClass=None):
        self.testComparisonClass = self.getClass(testComparisonClass, TestComparison)
        self.progressComparisonClass = self.getClass(progressComparisonClass, ProgressTestComparison)
    def getClass(self, given, defaultClass):
        if given:
            return given
        else:
            return defaultClass
    def __repr__(self):
        return "Comparing differences for"
    def __call__(self, test):
        newState = self.testComparisonClass(test.state, test.app)
        newState.computeFor(test)
        self.describe(test, newState.getPostText())
    def recomputeProgress(self, test, observers):
        if test.state.isComplete():
            if test.state.recalculateComparisons(test):
                newState = test.state.makeNewState(test.app, "recalculated")
                test.changeState(newState)
        else:
            newState = self.progressComparisonClass(test.state)
            newState.setObservers(observers)
            newState.computeFor(test)        
    def setUpSuite(self, suite):
        self.describe(suite)
    
class PrintObsoleteVersions(plugins.Action):
    scriptDoc = "Lists all files with version IDs that are equivalent to a non-versioned file"
    def __init__(self):
        self.filesToRemove = []
    def __repr__(self):
        return "Removing obsolete versions for"
    def __del__(self):
        if len(self.filesToRemove):
            print "Summary : Remove these files!"
            print "============================="
            for file in self.filesToRemove:
                print file         
    def __call__(self, test):
        self.describe(test)
        compFiles = {}
        resultFiles, defFiles = test.listStandardFiles(allVersions=True)
        for file in resultFiles:
            stem = file.split(".")[0]
            compFile = self.filterFile(test, file)
            if not compFiles.has_key(stem):
                compFiles[stem] = []
            compFiles[stem].append((file, compFile))
        for compFilesMatchingStem in compFiles.values():
            for index1 in range(len(compFilesMatchingStem)):
                for index2 in range(index1 + 1, len(compFilesMatchingStem)):
                    self.compareFiles(test, compFilesMatchingStem[index1], compFilesMatchingStem[index2])
                os.remove(compFilesMatchingStem[index1][1])
        
    def cmpFile(self, test, file):
        basename = os.path.basename(file)
        return mktemp(basename + "cmp")
    def filterFile(self, test, file):
        newFile = self.cmpFile(test, file)
        stem = os.path.basename(file).split(".")[0]
        runDepTexts = test.getCompositeConfigValue("run_dependent_text", stem)
        unorderedTexts = test.getCompositeConfigValue("unordered_text", stem)    
        from rundependent import RunDependentTextFilter
        filter = RunDependentTextFilter(runDepTexts, unorderedTexts, test.getRelPath())
        filter.filterFile(file, newFile)
        return newFile
    def compareFiles(self, test, filePair1, filePair2):
        origFile1, cmpFile1 = filePair1
        origFile2, cmpFile2 = filePair2
        if origFile1 in self.filesToRemove or origFile2 in self.filesToRemove:
            return
        if filecmp.cmp(cmpFile1, cmpFile2, 0):
            local1 = os.path.basename(origFile1)
            local2 = os.path.basename(origFile2)
            vlist1 = Set(local1.split(".")[2:])
            vlist2 = Set(local2.split(".")[2:])
            if vlist1.issuperset(vlist2):
                self.checkObsolete(test, origFile1, local1, origFile2)
            elif vlist2.issuperset(vlist1):
                self.checkObsolete(test, origFile2, local2, origFile1)
            else:
                print test.getIndent() + local1, "equivalent to", local2
    def checkObsolete(self, test, obsoleteFile, obsoleteLocal, causeFile):
        fallbackFile = self.getFallbackFile(test, obsoleteFile)
        if plugins.samefile(fallbackFile, causeFile):
            print test.getIndent() + obsoleteLocal, "obsolete due to", os.path.basename(causeFile)
            self.filesToRemove.append(obsoleteFile)
        else:
            print test.getIndent() + obsoleteLocal, "is a version-priority-fixing copy of", os.path.basename(causeFile)
    def getFallbackFile(self, test, fileName):
        parts = os.path.basename(fileName).split(".", 2)
        names = test.getAllFileNames(parts[0], parts[-1])
        if len(names) > 1:
            return names[-2]
        
    def setUpSuite(self, suite):
        self.describe(suite)
