from time import sleep
import cv2
import numpy as np
from collections  import namedtuple
from Logic.Global import printf
from Logic        import Paths

class Vision:

    def __init__(self, vStream):

        # How long the "tracker history" array is (how many frames of tracked data are kept)
        self.historyLen = 60

        self.vStream        = vStream
        self.exiting        = False
        self.planeTracker   = PlaneTracker(25.0, self.historyLen)
        self.cascadeTracker = CascadeTracker(self.historyLen)

        # Use these on any work functions that are intended for threading
        self.filterLock  = self.vStream.filterLock
        self.workLock    = self.vStream.workLock

    # Wrappers for the VideoStream object
    def waitForNewFrames(self, numFrames=1):
        # Useful for situations when you need x amount of new frames after the robot moved, before doing vision

        for i in range(0, numFrames):

            lastFrame = self.vStream.frameCount
            while self.vStream.frameCount == lastFrame:
                if self.exiting:
                    printf("Vision.waitForNewFrames(): Exiting early!")
                    break

                sleep(.05)


    # All tracker control functions


    # All Tracker Controls
    def addPlaneTarget(self, trackable):
        if trackable is None:
            printf("Vision.addPlaneTarget(): ERROR: Tried to add nonexistent trackable to the tracker!")
            return

        views = trackable.getViews()
        with self.workLock:
            for view in views:
                self.planeTracker.addView(view)
        # Make sure that the work and filter trackers are present
        self.vStream.addWork(self.planeTracker.track)
        self.vStream.addFilter(self.planeTracker.drawTracked)

    def addCascadeTarget(self, targetID):
        if type(targetID) is not str:
            print("ERROR ERROR ERROR IN VISION")
        self.cascadeTracker.addTarget(targetID)

        # Make sure that the tracker and filter are activated
        self.vStream.addWork(self.cascadeTracker.track)
        self.vStream.addFilter(self.cascadeTracker.drawTracked)

    def endAllTrackers(self):
        # End all trackers and clear targets

        with self.workLock:
            self.planeTracker.clear()
            self.cascadeTracker.clear()

        # Shut down and reset any cascade tracking
        self.vStream.removeWork(self.cascadeTracker.track)
        self.vStream.removeFilter(self.cascadeTracker.drawTracked)

        # Shut down and reset any planeTracking


        self.vStream.removeWork(self.planeTracker.track)
        self.vStream.removeFilter(self.planeTracker.drawTracked)


    # PlaneTracker Search Functions
    def getObjectLatestRecognition(self, trackable):
        # Returns the latest successful recognition of objectID, so the user can pull the position from that
        # it also returns the age of the frame where the object was found (0 means most recently)

        with self.workLock:
            trackHistory = self.planeTracker.trackedHistory[:]

        for frameID, historyFromFrame in enumerate(trackHistory):
            for tracked in historyFromFrame:
                if trackable.equalTo(tracked.view.name):
                    return frameID, tracked
        return None, None

    def getObjectBruteAccurate(self, trackable, minPoints=-1, maxFrameAge=0, maxAttempts=1):
        """
        This will brute-force the object finding process somewhat, and ensure a good recognition, or nothing at all.

        :param trackable: The TrackableObject you intend to find
        :param minPoints:    Minimum amount of recognition points that must be found in order to track. -1 means ignore
        :param maxFrameAge:  How recent the recognition was, in "frames gotten from camera"
        :param maxAttempts:  How many frames it should wait for before quitting the search.
        :return:
        """


        # Get a super recent frame of the object
        for i in range(0, maxAttempts):
            if self.exiting:
                printf("Vision.getObjectBruteAccurate(): Exiting early!")
                break

            # If the frame is too old or marker doesn't exist or doesn't have enough points, exit the function
            frameAge, trackedObj = self.getObjectLatestRecognition(trackable)

            if trackedObj is None or frameAge > maxFrameAge or trackedObj.ptCount < minPoints:
                if i == maxAttempts - 1: break

                self.waitForNewFrames()
                continue

            # If the object was successfully found with the correct attributes, return it
            return trackedObj

        return None

    def getObjectSpeedDirectionAvg(self, trackable, samples=3, maxAge=20, isSameObjThresh=50):
                # TEST CODE FOR VISION
        with self.workLock:
            trackHistory = self.planeTracker.trackedHistory[:maxAge]

        hst      = []
        # Get 'samples' amount of tracked object from history, and the first sample has to be maxAge less then the last
        for frameAge, historyFromFrame in enumerate(trackHistory):
            #
            # # If the first finding of the object is older than maxAge
            # if len(hst) == 0 and frameAge > maxAge - samples: return None, None, None

            for tracked in historyFromFrame:
                if trackable.equalTo(tracked.view.name):
                    # If it's the first object
                    if len(hst) == 0:
                        hst.append(tracked.center)
                        break

                    c = tracked.center
                    dist = ((hst[0][0] - c[0]) ** 2 + (hst[0][1] - c[1]) ** 2 + (hst[0][2] - c[2]) ** 2) ** .5


                    if dist < isSameObjThresh:
                        hst.append(tracked.center)
                        break
            if len(hst) >= samples: break

        if len(hst) == 0: return None, None, None

        # Get the "noise" of the sample
        hst     = np.float32(hst)
        avgPos  = hst[0]
        avgDir  = np.float32([0, 0, 0])
        for i, pt in enumerate(hst[1:]):
            avgDir += np.float32(hst[i]) - pt
            avgPos += pt

        avgDir /= samples - 1
        avgMag  = sum(avgDir ** 2) ** .5
        avgPos /= samples
        return avgPos, avgMag, avgDir

    def searchTrackedHistory(self, trackable=None, maxAge=None, minPtCount=None):
        """
        Search through trackedHistory to find an object that meets the criteria

        :param trackableObject: Specify if you want to find a particular object
        :param maxAge:        Specify if you wannt to find an object that was found within X frames ago
        :param minPtCount:      Specify if you want to find an object with a minimum amount of tracking points
        """

        maxFrame = maxAge + 1
        if maxFrame is None or maxFrame >= self.historyLen:
            printf("Vision.isRecognized(): ERROR: Tried to look further in the history than was possible!")
            maxFrame = self.historyLen

        # Safely pull the relevant trackedHistory from the tracker object
        with self.workLock:
            trackHistory = self.planeTracker.trackedHistory[:maxFrame]


        # Check if the object was recognized in the most recent frame. Check most recent frames first.
        for historyFromFrame in trackHistory:
            for tracked in historyFromFrame:
                # If the object meets the criteria
                if trackable is not None and not trackable.equalTo(tracked.view.name): continue

                if minPtCount is not None and not tracked.ptCount > minPtCount: continue
                # print("Found object ", tracked.view.name, " with pts, ", tracked.ptCount, "maxFrames", maxFrame)
                return tracked
        return None



    # Face Tracker Search Functions
    def isFaceDetected(self):
        # Safely pull the relevant trackedHistory from the tracker object
        with self.workLock:
            trackHistory = self.cascadeTracker.trackedHistory[0]

        if len(trackHistory) > 0:
            return True
        return None


    # General use computer vision functions
    def getMotion(self):

        # GET TWO CONSECUTIVE FRAMES
        frameList = self.vStream.getFrameList()
        if len(frameList) < 10:  # Make sure there are enough frames to do the motion comparison
            printf("getMovement():Not enough frames in self.vid.previousFrames")
            return 0  # IF PROGRAM IS RUN BEFORE THE PROGRAM HAS EVEN 10 FRAMES

        frame0 = frameList[0]
        frame1 = frameList[5]


        movementImg = cv2.absdiff(frame0, frame1)
        avgDifference = cv2.mean(movementImg)[0]

        return avgDifference

    def getColor(self, **kwargs):
        # Get the average color of a rectangle in the main frame. If no rect specified, get the whole frame
        p1 = kwargs.get("p1", None)
        p2 = kwargs.get("p2", None)

        frame = self.vStream.getFrame()
        if p1 is not None and p2 is not None:
            frame = frame[p2[1]:p1[1], p2[0]:p1[0]]

        averageColor = cv2.mean(frame)  # RGB
        return averageColor

    def getRange(self, hue, tolerance):
        # Input an HSV, get a range
        low = hue - tolerance / 2
        high = hue + tolerance / 2

        if low < 0:   low += 180
        if low > 180: low -= 180

        if high < 0:   high += 180
        if high > 180: high -= 180

        if low > high:
            return int(high), int(low)
        else:
            return int(low), int(high)

    def findObjectColor(self, hue, tolerance, lowSat, highSat, lowVal, highVal):
        low, high = self.getRange(hue, tolerance)

        hue = int(hue)
        tolerance = int(tolerance)
        lowSat = int(lowSat * 255)
        highSat = int(highSat * 255)
        lowVal = int(lowVal * 255)
        highVal = int(highVal * 255)

        frame = self.vStream.getFrame()
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        if hue - tolerance < 0 or hue + tolerance > 180:
            # If the color crosses 0, you have to do two thresholds
            lowThresh = cv2.inRange(hsv, np.array((0, lowSat, lowVal)), np.array((low, highSat, highVal)))
            upperThresh = cv2.inRange(hsv, np.array((high, lowSat, lowVal)), np.array((180, highSat, highVal)))
            finalThresh = upperThresh + lowThresh
        else:
            finalThresh = cv2.inRange(hsv, np.array((low, lowSat, lowVal)), np.array((high, highSat, highVal)))

        cv2.imshow(str(lowSat), finalThresh.copy())
        cv2.waitKey(1)

        contours, hierarchy = cv2.findContours(finalThresh, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

        cv2.imshow("frame", finalThresh)
        cv2.waitKey(1)
        # Find the contour with maximum area and store it as best_cnt
        max_area = 0
        best_cnt = None
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area > max_area:
                max_area = area
                best_cnt = cnt

        if best_cnt is not None:
            M = cv2.moments(best_cnt)
            cx, cy = int(M['m10'] / M['m00']), int(M['m01'] / M['m00'])
            # cv2.circle(frame, (cx, cy), 5, 255, -1)
            return [cx, cy]
        return None

    def bgr2hsv(self, colorBGR):
        """
        Input: A tuple OR list of the format (h, s, v)
        OUTPUT: A tuple OR list (depending on what was sent in) of the fromat (r, g, b)
        """
        isList = colorBGR is list

        r, g, b = colorBGR[2], colorBGR[1], colorBGR[0]

        r, g, b = r / 255.0, g / 255.0, b / 255.0
        mx = max(r, g, b)
        mn = min(r, g, b)
        df = mx - mn
        if mx == mn:
            h = 0
        elif mx == r:
            h = (60 * ((g - b) / df) + 360) % 360
        elif mx == g:
            h = (60 * ((b - r) / df) + 120) % 360
        elif mx == b:
            h = (60 * ((r - g) / df) + 240) % 360
        if mx == 0:
            s = 0
        else:
            s = df / mx
        v = mx

        if isList:
            return [h, s, v]
        else:
            return h, s, v

    def crop(self, image, rect):
        # Just pass an image, and a tuple/list of (x1,y1, x2,y2)
        return image[rect[1]:rect[3], rect[0]:rect[2]]


    # Vision specific functions
    def setExiting(self, exiting):
        # Used for closing threads quickly, when this is true any time-taking functions will skip through quickly
        # and return None or False or whatever their usual failure mode is. ei, waitForFrames() would exit immediately
        if exiting:
            printf("Vision.setExiting(): Setting Vision to Exiting mode. All frame commands should exit quickly.")
            self.endAllTrackers()

        self.exiting = exiting


class Tracker:
    def __init__(self, historyLength):
        self.historyLen = historyLength
        self.targets      = []
        self.trackedHistory = [[] for i in range(self.historyLen)]

    def _addTracked(self, trackedArray):
        # Add an array of detected objects to the self.trackedHistory array, and shorten the trackedHistory array
        # so that it always remains self.historyLength long
        self.trackedHistory.insert(0, trackedArray)

        while len(self.trackedHistory) > self.historyLen:
            del self.trackedHistory[-1]

    def clear(self):
        self.targets = []


class PlaneTracker(Tracker):
    """
    PlanarTarget:
        image     - image to track
        rect      - tracked rectangle (x1, y1, x2, y2)
        keypoints - keypoints detected inside rect
        descrs    - their descriptors
        data      - some user-provided data

    TrackedTarget:
        target - reference to PlanarTarget
        p0     - matched points coords in target image
        p1     - matched points coords in input frame
        H      - homography matrix from p0 to p1
        quad   - target bounary quad in input frame
    """
    PlaneTarget  = namedtuple('PlaneTarget', 'view, keypoints, descrs')

    # target: the "sample" object of the tracked object. Center: [x,y,z] Rotation[xr, yr, zr], ptCount: matched pts
    TrackedPlane = namedtuple('TrackedPlane', 'view, target, quad, ptCount, center, rotation, p0, p1, H,')

    # Tracker parameters
    FLANN_INDEX_KDTREE = 1
    FLANN_INDEX_LSH    = 6
    MIN_MATCH_COUNT    = 15

    # Check Other\Notes\FlanParams Test Data to see test data for many other parameters I tested for speed and matching
    flanParams         = dict(algorithm         = FLANN_INDEX_LSH,
                              table_number      =              6,  #  3,  #  6,  # 12,
                              key_size          =             12,  # 19,  # 12,  # 20,
                              multi_probe_level =              1)  # 1)   #  1)  #  2)


    def __init__(self, focalLength, historyLength):
        super(PlaneTracker, self).__init__(historyLength)
        self.focalLength  = focalLength
        self.detector     = cv2.ORB_create(nfeatures = 8000)

        # For ORB
        self.matcher      = cv2.FlannBasedMatcher(self.flanParams, {})  # bug : need to pass empty dict (#1329)
        self.framePoints  = []


        # trackHistory is an array of arrays, that keeps track of tracked objects in each frame, for hstLen # of frames
        # Format example [[PlanarTarget, PlanarTarget], [PlanarTarget], [PlanarTarget...]...]
        # Where trackedHistory[0] is the most recent frame, and trackedHistory[-1] is about to be deleted.

    def createTarget(self, view):
        """
        There's a specific function for this so that the GUI can pull the objects information and save it as a file
        using objectManager. Other than that special case, this function is not necessary for normal tracker use
        """

        # Get the PlanarTarget object for any name, image, and rect. These can be added in self.addTarget()
        x0, y0, x1, y1         = view.rect
        points, descs          = [], []

        raw_points, raw_descrs = self.__detectFeatures(view.image)

        for kp, desc in zip(raw_points, raw_descrs):
            x, y = kp.pt
            if x0 <= x <= x1 and y0 <= y <= y1:
                points.append(kp)
                descs.append(desc)


        descs  = np.uint8(descs)
        target = self.PlaneTarget(view=view, keypoints=points, descrs=descs)

        # If it was possible to add the target
        return target

    def addView(self, view):
        # This function checks if a view is currently being tracked, and if not it generates a target and adds it

        for target in self.targets:
            if view == target.view:
                printf("PlaneTracker.addTarget(): Rejected: Attempted to add two targets of the same name: ", view.name)
                return

        planarTarget = self.createTarget(view)

        descrs = planarTarget.descrs
        self.matcher.add([descrs])
        self.targets.append(planarTarget)


    def clear(self):
        # Remove all targets
        self.targets = []
        self.matcher.clear()

    def track(self, frame):
        # updates self.tracked with a list of detected TrackedTarget objects
        self.framePoints, frame_descrs = self.__detectFeatures(frame)
        tracked = []


        # If no keypoints were detected, then don't update the self.trackedHistory array
        if len(self.framePoints) < self.MIN_MATCH_COUNT:
            self._addTracked(tracked)
            return


        matches = self.matcher.knnMatch(frame_descrs, k = 2)
        matches = [m[0] for m in matches if len(m) == 2 and m[0].distance < m[1].distance * 0.75]

        if len(matches) < self.MIN_MATCH_COUNT:
            self._addTracked(tracked)
            return


        matches_by_id = [[] for _ in range(len(self.targets))]
        for m in matches:
            matches_by_id[m.imgIdx].append(m)

        tracked = []

        for imgIdx, matches in enumerate(matches_by_id):

            if len(matches) < self.MIN_MATCH_COUNT:
                continue

            target = self.targets[imgIdx]

            p0 = [target.keypoints[m.trainIdx].pt for m in matches]
            p1 = [self.framePoints[m.queryIdx].pt for m in matches]
            p0, p1 = np.float32((p0, p1))
            H, status = cv2.findHomography(p0, p1, cv2.RANSAC, 3.0)

            status = status.ravel() != 0
            if status.sum() < self.MIN_MATCH_COUNT: continue


            p0, p1 = p0[status], p1[status]

            x0, y0, x1, y1 = target.view.rect

            quad = np.float32([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
            quad = cv2.perspectiveTransform(quad.reshape(1, -1, 2), H).reshape(-1, 2)


            # Calculate the 3d coordinates of the object
            center, rotation = self.get3DCoordinates(frame, target.view.rect, quad)

            track = self.TrackedPlane(target=target,
                                      view=target.view,
                                      quad=quad,
                                      ptCount=len(matches),
                                      center=center,
                                      rotation=rotation,
                                      p0=p0, p1=p1, H=H, )
            tracked.append(track)


        tracked.sort(key = lambda t: len(t.p0), reverse=True)

        self._addTracked(tracked)


    def __detectFeatures(self, frame):
        cv2.ocl.setUseOpenCL(False)  # THIS FIXES A ERROR BUG: "The data should normally be NULL!"

        # detect_features(self, frame) -> keypoints, descrs
        keypoints, descrs = self.detector.detectAndCompute(frame, None)
        if descrs is None:  # detectAndCompute returns descs=None if not keypoints found
            descrs = []
        return keypoints, descrs

    def drawTracked(self, frame):
        filterFnt   = cv2.FONT_HERSHEY_PLAIN
        filterColor = (255, 255, 255)


        # Draw the Name and XYZ of the object
        for tracked in self.trackedHistory[0]:
            quad = np.int32(tracked.quad)
            cv2.polylines(frame, [quad], True, (255, 255, 255), 2)

            # Figure out how much the text should be scaled (depends on the different in curr side len, and orig len)
            rect          = tracked.view.rect
            origLength    = rect[2] - rect[0] + rect[3] - rect[1]
            currLength    = np.linalg.norm(quad[1] - quad[0]) + np.linalg.norm(quad[2] - quad[1])  # avg side len
            scaleFactor   = currLength / origLength

            # Draw the name of the object, and coordinates
            cv2.putText(frame, tracked.view.name, tuple(quad[1]),
                        filterFnt, scaleFactor, color=filterColor, thickness=1)

            # FOR DEUBGGING ONLY: TODO: Remove this when deploying final product
            try:
                coordText =  "X " + str(int(tracked.center[0])) + \
                            " Y " + str(int(tracked.center[1])) + \
                            " Z " + str(int(tracked.center[2]))
                            # " R " + str(round(tracked.rotation[2], 2))
                cv2.putText(frame, coordText, (quad[1][0], quad[1][1] + int(15*scaleFactor)),  filterFnt, scaleFactor, color=filterColor, thickness=1)
            except:
                pass

            for (x, y) in np.int32(tracked.p1):
                cv2.circle(frame, (x, y), 2, (255, 255, 255))

        return frame


    # Thread safe
    def get3DCoordinates(self, frame, rect, quad):
        # Do solvePnP on the tracked object
        x0, y0, x1, y1 = rect
        width  = (x1 - x0) / 2
        height = (y1 - y0) / 2
        quad3d = np.float32([[     -width,      -height, 0],
                              [     width,      -height, 0],
                              [     width,       height, 0],
                              [    -width,       height, 0]])
        fx              = 0.5 + self.focalLength / 50.0
        dist_coef       = np.zeros(4)
        h, w            = frame.shape[:2]

        K = np.float64([[fx * w,      0, 0.5 * (w - 1)],
                        [     0, fx * w, 0.5 * (h - 1)],
                        [   0.0,    0.0,          1.0]])
        ret, rotation, center = cv2.solvePnP(quad3d, quad, K, dist_coef)
        return list(map(float,center)), list(map(float,rotation))


class CascadeTracker(Tracker):
    # This tracker is intended for tracking Haar cascade objects that are loaded with the program
    CascadeTarget  = namedtuple('CascadeTarget', 'name, classifier, minPts')

    def __init__(self, historyLength):
        super(CascadeTracker, self).__init__(historyLength)

        self.cascades = [self.CascadeTarget(name       = "Face",
                                            classifier = cv2.CascadeClassifier(Paths.face_cascade),
                                            minPts     = 20),

                         self.CascadeTarget(name       = "Smile",
                                            classifier = cv2.CascadeClassifier(Paths.smile_cascade),
                                            minPts     = 30)]

    def addTarget(self, targetName):
        for target in self.cascades:
            if targetName == target.name:
                if target not in self.targets:
                    self.targets.append(target)
                else:
                    printf("CascadeTracker.addTarget(): ERROR: Tried to add a target that was already there!")

    def track(self, frame):
        gray  = cv2.cvtColor(frame.copy(), cv2.COLOR_BGR2GRAY)

        tracked = []
        # Track any cascades that have been added to self.targets
        for target in self.targets:
            foundList = target.classifier.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=15, minSize=(30, 30))

            # If faces were found, append them here
            for found in foundList:
                tracked.append(found)


        self._addTracked(tracked)

    def drawTracked(self, frame):
        for tracked in self.trackedHistory[0]:
            (x, y, w, h) = tracked
            cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 255, 255), 2)

# def getMotionDirection(self):
    #     frameList = self.vStream.getFrameList()
    #
    #     frame0 = cv2.cvtColor(frameList[-1].copy(), cv2.COLOR_BGR2GRAY)
    #     frame1 = cv2.cvtColor(frameList[-2].copy(), cv2.COLOR_BGR2GRAY)
    #
    #     flow = cv2.calcOpticalFlowFarneback(frame1, frame0, 0.5,   1,  5,              1,             5,  5, 2)
    #
    #     avg = cv2.mean(flow)
    #     copyframe = frameList[-1].copy()
    #     cv2.line(copyframe, (320, 240), (int(avg[0] * 100 + 320), int(avg[1] * 100 + 240)), (0, 0, 255), 5)
    #     cv2.imshow("window", copyframe)
    #     cv2.waitKey(1)
    #     return avg


"""
# DEPRECATED VISION FUNCTIONS
    def getAverageObjectPosition(self, objectID, numFrames):
        # Finds the object in the latest numFrames from the tracking history, and returns the average pos and rot

        if numFrames >= self.tracker.historyLen:
            printf("Vision.getAverageObjectPosition(): ERROR: Tried to look further in the history than was possible!")
            numFrames = self.tracker.historyLen


        trackHistory = []
        with self.workLock:
            trackHistory = self.tracker.trackedHistory[:numFrames]

        # Set up variables
        samples       = 0
        locationSum   = np.float32([0, 0, 0])
        rotationSum   = np.float32([0, 0, 0])

        # Look through the history range and collect the object center and rotation
        for frameID, historyFromFrame in enumerate(trackHistory):

            for obj in historyFromFrame:

                if obj.target.name == objectID:
                    locationSum += np.float32(obj.center)
                    rotationSum += np.float32(obj.rotation)
                    samples     += 1

        # If object was not found, None will be returned for the frame and the object
        if samples == 0:
            return None, None

        return tuple(map(float, locationSum/samples)), tuple(map(float, rotationSum/samples))

"""