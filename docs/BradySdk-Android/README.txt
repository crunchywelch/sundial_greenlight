PLEASE READ THE FOLLOWING:
=========================


If this .zip was downloaded directly from bradyid.com, the following applies to you:

This .aar file is essentially the Brady Android SDK. However, the following 3rd party
libraries must also be included in order for the SDK to fully work. Therefore, it is
HIGHLY suggested to add the SDK using the properly packaged version at:
https://central.sonatype.com/artifact/com.bradyid/BradySdk/overview

To do this, copy and paste the following line into your app's build.gradle file and
IGNORE the additional direction block below.

******************************************
implementation 'com.bradyid:BradySdk:3.1.0'
******************************************


------------------------------------------------------------------------------------
COPY AND PASTE THE FOLLOWING DEPENDENCIES IN YOUR APP'S "BUILD.GRADLE":

implementation files('libs/BradySdk-3.1.0.aar')
implementation 'com.google.zxing:core:3.5.3'
implementation 'com.fasterxml.jackson.core:jackson-core:2.17.1'
implementation 'com.fasterxml.jackson.core:jackson-annotations:2.17.1'
implementation 'com.fasterxml.jackson.core:jackson-databind:2.17.1'
implementation 'com.fasterxml.jackson.datatype:jackson-datatype-jsr310:2.17.1'
implementation 'com.google.android.gms:play-services-tasks:18.2.0'
implementation 'com.google.firebase:protolite-well-known-types:18.0.0'
implementation 'com.google.android.gms:play-services-gcm:17.0.0'
implementation 'androidx.test:core:1.6.1'
implementation 'androidx.test:rules:1.6.1'
implementation 'androidx.test:runner:1.6.1'
implementation 'org.lz4:lz4-java:1.8.0'
implementation 'com.google.firebase:firebase-crashlytics-buildtools:3.0.2'
implementation 'com.squareup.okhttp3:okhttp:4.12.0'

Lastly, drop the .aar file into a folder named "libs" in your app's root directory
------------------------------------------------------------------------------------

Release Notes (Android)

###3.1.0

Release 5/9/2025

- Added support for the i7500 printer:
	- Bluetooth Low Energy connection
	- Wi-Fi connection
	- Prints all supported objects including bitmap printing
	- Does not support MANUAL supply
- Added CutOption named "CutAfterRow".
	- Only the M611, S3700, i5300, and i7500 support this command. All other printers will throw an IllegalArgumentException if used.
	- This must be used in tandem with "PrintingOptions.setCutAfterRowValue(2)"
- Added a PrintingOptions method named "setCutAfterRowValue" that takes an integer to specify how many labels to cut after.
	- For example, setting this value to 2 will cut after every 2nd label
- Added CutOption named "UsePrinterSettings".
	- This is only supported on the i7500 if there is post print accessory installed. All other printers will throw an IllegalArgumentException if used.
	- This setting will use whichever CutOption is configured on the printer itself.
- Added a PrinterDetail method named "getPostPrintAccessoryType" that returns the name of the accessory installed on the connected i7500.
	- Will default to PostPrintAccessoryType.None for all other printers.
- Added a PrinterDetail method named "isDirectThermalSupply" that returns true/false if the installed part is Direct Thermal.
- Added a PrinterDetail method named "getDotsPerInch" that returns the dots per inch capability of the connected printer.
- Fixed bug where apps with SdkVersion > 32 were not able to enable Fine Location permission for Wi-Fi discovery and connection.

###3.0.0

Release 9/9/2024

- Added support for the S3700 printer:
	- Bluetooth Low Energy connection
	- Wi-Fi connection
	- Prints all supported objects
	- **Cuts all supported objects designed as Cut objects**
- Added support for the i5300 printer:
	- Bluetooth Classic connection (Bluetooth Low Energy not supported)
	- Wi-Fi connection
	- Prints all supported objects
- Added color support to print previews:
	- Before version 3.0.0, print previews were only black text on white backgrounds.
	- Version 3.0.0+ print preview correctly show the color of the ribbon and supply.
- Added API method getSupplyColor to PrinterDetails
- Added API method getRibbonColor to PrinterDetails
- API method getPreview now takes a 4th parameter that passes in PrinterDetails:
	- This is mandatory if a user wants the print preview to reflect color.
	- Null may be passed-in, but the print preview will always be black on white.
	- Additional features added in the future will also use PrintDetails to more accurately display a print preview.
- Improvements to monochromization of bitmap images and Graphic objects.
- Fixed rendering bug of BWS Graphic objects.
- Fixed rendering bug of labels designed with the BWS Text Labels app. 

###2.0.1

Release 7/25/2024

- Updated minSdkVersion to 26
- Fixed M611 connection issues.
	- This was due to classes from third-party libraries being removed at compilation.

###2.0.0

Release 7/15/2024

- Added support for M610 and M710 printers.
- Now logs analytics for print jobs.
	- You may disable the capturing of app data by adding the following:
```
Analytics analytics = AnalyticsFactory.getAnalytics(context.getApplicationContext());
analytics.setTrackingEnabled(false);
```
- Added support for Date Time Objects in Brady Workstation templates.
- Added support for Cable/Wire Wrap placeholders in templates created with Brady Workstation's Text Labels application.
- Added support to handle Group Entities from a Brady Workstation template.
- Improved image quality of Bitmap and ImageEntity printing.
- API methods:
	- Added the **printerRemoved()** method to PrinterDiscoveryListener. This will be triggered when the corresponding printer has not been seen in the area for 10 seconds. The user can decide if they want to remove it from the printer list they've displayed in their UI.
	- Added **getConnectionType()** API method to DiscoveredPrinterInformation to specify which protocol the printer was discovered over.
	- Added **SupplyColor** and **SupplyInvalid** to **PrinterProperties.java**
	- Changed **checkForPartMismatch(Template template)** --> **checkForSupplyMismatch(Template template)**
	- Changed **getSubstrateWidthInInches()** --> **getSupplyWidth()**
	- Changed **getSubstrateHeightInInches()** --> **getSupplyHeight()**
	- Changed **getSubstrateLeftOffset()** --> **getSupplyLeftOffset()**
	- Changed **getSubstrateVerticalOffset()** --> **getSupplyVerticalOffset()**
	- Changed **getPartInfo()** --> **getSupplyName()**
	- Changed **cutLabel()** --> **cutSupply()**
	- Changed **feed()** --> **feedSupply()**
	- Changed **turnOff()** --> **setAutomaticShutdownTime()**
- Reworked how custom exceptions work:
	- Every API method can now be wrapped in a try/catch with **SdkApiException** always being the base exception that will be thrown.
	- If you catch an **SdkApiException**, the message will provide a more specific cause to the error and how to resolve it. 
- Fixed a bug with **checkForPartMismatch()** where related supply parts were not considered a match. Before, this only returned true when an exact match was found.
- Fixed a bug where Code128 values were not being validated correctly.
- Fixed a bug where text objects would always appear bolded.
- Fixed UPC barcode rendering bugs.
- Fixed Text Object bugs related to text wrapping and fit to frame.

###1.7.1

Release 4/25/2024

- Removed all embedded fonts to substantially decrease the published library's size.
	- This functionality is replaced with the "storeFonts" API method.

###1.7.0

Release 4/25/2024

- Added the "storeFonts" API method to Template.java that allows users to cache their own fonts. If a template was designed with one of these fonts, it will properly use the font when previewing and printing.
- Added permissions to the AndroidManifest.xml to stay consistent with Brady's mobile application "Express Labels":
	- ACCESS_NETWORK_STATE
	- ACCESS_WIFI_STATE
	- CHANGE_NETWORK_STATE
	- NEARBY_WIFI_DEVICES
- Fixed bug with the third-party JSON desrialization library that only existed in release builds.
- Fixed bug when bitmap printing where multiple copies would print an incorrect amount of labels.

###1.6.0

Release 4/4/2024

- Now integrates the Brady Parts Database:
	- This file stores accurate label dimensions of every existing part for the supported printers. This makes both the print preview and printing more reliable and accurate.
- Greatly improved default Bitmap Printing:
	- With the addition of the Brady Parts Database, printing an image (.png, .jpg, etc.) will now be scaled to print in the first printable zone of the installed label.
	- When printing, images should always fit on the label (should never be "cut off").
- Improved accuracy of print preview zone drawing.
- Added API methods to PrinterDetails:
	- **getSubstrateLeftOffset()** - Get's the currently installed parts left offset dimension in inches as a double.
	- **getSubstrateVerticalOffset()** - Get's the currently installed part's vertical offset dimension in inches as a double.
- Added the properties **SupplyLeftOffset** and **SupplyVerticalOffset** to the API's PrinterProperties.java
- Labels designed in the Express Labels mobile app will now correctly deserialize and print.
- Fixed a bug where an M611 printer error would "lock up" the Monitoring Engine preventing further updates or printing.
- Fixed a bug where non-authentic M211 parts would prevent printing.
- Fixed small PrinterDetails bugs related to the M511.

###1.5.2

Released 1/24/2024

- Added disconnectWithoutForget() API method to disconnect without forgetting the printer for future auto-conencts.
- Added forgetLastConnectedPrinter() API method to simply forget the printer internally to cancel future auto-connects.

**These two API methods combined are equal to simply calling the original disconnect() method**

- Fixed bug where lastConnectedPrinter was not being correctly initialized, populated, or cleared.

###1.5.1

Released 11/28/2023

- Implemented Fit to Frame functionality with barcodes.
- Fixed Barcode bug where barcodes were not centering after resizing if Fit to Frame is toggled off in the template.

###1.5.0

Released 11/10/2023

- Added an alternative API print method to allow the specification of the bitmap width and the label length when bitmap printing.
- Added "getIsSupplyPreSized()" API method to PrinterDetails to allow the user to know if the installed part inside the connected printer is pre-sized or an alternative type such as continuous.
- Changed PrinterUpdate Status messages back to their "key" values. These are constants that are returned from the SDK that can be used to determine what state the printer is in.
	- **For Example**: A user could put a conditional inside PrinterUpdate to check when the printer changes to the "disconnected" state. If **printerDetails.getPrinterStatusMessage == "PrinterStatus_Disconnected"** then the user could make a toast appear on the screen that says "Disconnected".
- Fixed some small BLE view model bugs that were incorrectly triggering inaccurate Printer Updates.
- If an attempted BLE connection results in a connection timeout, it now retries until the Bluetooth Gatt can make a valid connection.

###1.4.7

Released 10/25/2023

- Fixed bug where printing a bitmap to an M611 was causing crashes and scaling incorrectly.
- Fixed bug where the print() API method was not waiting until the print job was finished to return the acurrate result.

###1.4.6

Released 10/17/2023

- Fixed bug where View Model was out of sync. This was causing possible connect and disconnect issues. These issues could be replicated if an app depends on receiving Printer Updates from the SDK to control other functionalities.

###1.4.5

Released 10/11/2023

- Add Collating property in API PrintOptions class to allow support for collating.
- Fixed bug printing multiple copies of the same label.
- Fixed bug printing with the CutOption EndOfJob.

###1.4.4

Released 9/25/2023

- Added implementation of Rotating objects.
- Fixed M511 Disconnection bug.
- Fixed a View Model repeated updates bug.
- Fixed other small null errors.

###1.4.3

Released 9/11/2023

- Includes the removal of the Bluetooth Background Location permission.

1.4.2

Released 8/24/2023

- Changed the reconnect() API method to return a boolean representing the success of the call.
- Increased the connection timeouts which was necessary for older devices and the M611 Latimer.
- Implemented rotation to rendered text. Example: If you have rotated an object in a BWS template, it will now render and print how it appears in BWS accurately.

1.4.1

Released 8/9/2023

- Fixed the reconnect() API method
- Fixed an issue where successfully connecting would not store the printer for later use. This was due to a JSON error and was preventing automatic connection.
- Fixed the printing multiple copies feature for the M211 (the CutOption "EndOfLabel" works the same as the CutOption "Never" currently).
- Fixed a wrongly set barcode value bug in QR Code, DataMatrix, and Code128 barcodes.

1.4.0

Released 7/31/2023

- HaveOwnership() API method was moved from PrinterDetails to PrinterDiscovery.
- setTemplate() API method added to alternatively allow the "passing in" of a file name and it's location.
- DataMatrix, QR Code, and Code128 bug fixes.
- Improperly disconnecting bug fix.
- Added LZ4 compression and decrompression for connection to an M611 Latimer (faster connection).

1.3.4

Released 7/14/2023

- Fixed errors in auto-connection for Bluetooth Classic and Wifi devices.

1.3.3

Released 6/27/2023

- Fixed a bug preventing connection to a Bluetooth Classic printer with a device under Android 12.
- Removed java tuples library dependency so the SDK no longer requires use of Triplet objects.
- Preparation to allow the use of other framework bindings.

1.3.2

Released 4/6/2023

- Fixed a Draw Image bug in DroidDrawingContext to accurately print an image how it appears in the preview rendering.
- Fixed a Label Trailer bug where the trailer flag in the print() API method wasn't changing anything.
- Fixed a DateTimeObject bug where printer objects were not serializing correctly from the Maven Central dependency only. This was also causing the DiscoveredPrinterInformation is null bug.
- Updated the URL metadata for the Maven Central site so that https://sdk.bradyid.com is now embedded on the Maven Central page for the BradySdk.

1.3.1

Released 3/24/2023

- Fixed a preview bug with how the unprintable zones (the grey area in previews) are oriented.
- Fixed a bug relating to the automatic connection to an M611 via Bluetooth Low Energy.
- Fixed a text alignment bug where text with center alignment was defaulting to left alignment.
- Improved the clarity of QR codes when they print and render while also changing the error correction to Q.

- Now allows the rendering and printing of .png, .jpg, .jpeg, .svg, and other image files via:
```
//Instead of requiring the use of .BWT or .BWS files,
//we now support the rendering and printing of image files using this alternative constructor.
PrinterDetails.print(context, bitmap, printingOptions, false);
```

- Now allows a user to add the Android SDK to their app with a single dependency. Reference the [Setup](https://sdk.bradyid.com/android_studio/) page.
```
implementation 'com.bradyid:BradySdk:1.3.1'
```

1.3.0

Released 1/17/2023

Includes 5 API changes made to ensure that our Android SDK is consistent with our iOS SDK in order to provide clarity and ease of use in the future.

- **PrinterDiscoveryImpl** is no longer accessible and will instead be handled internally. Therefore, to retrieve the new PrinterDiscovery object, users will replace your PrinterDiscoveryImpl initialization with:

```
List<PrinterDiscoveryListener> printerDiscoveryListeners = new ArrayList<>();
printerDiscoveryListeners.add(this);

PrinterDiscovery printerDiscovery = PrinterDiscoveryFactory.getPrinterDiscovery(getApplicationContext(), printerDiscoveryListeners);
```

Users will still be able to call the same methods from this PrinterDiscovery object as users did with the PrinterDiscoveryImpl object.

- **PrinterDisoveryListener** will now be required to retrieve any discovered printer. Implementing this to your UI may look like this:

```
public class MainActivity implements PrinterDiscoveryListener {
```


This will add the interface’s override methods to your class. These methods are:
```
printerDiscovered(DiscoveredPrinterInformation dpi)
printerDiscoveryStarted()
printerDiscoveryStopped()
```			
These will all trigger automatically when certain things happen in the SDK. For example, printerDiscovered will be called automatically when a printer is discovered, handing you the discovered printer object in the method’s body. **printerDiscoveryStarted** and **printerDiscoveryStopped** will be called automatically when a scan is started or stopped. 

This change gives our users more freedom because they can keep a list of printers by adding the found DiscoveredPrinterInformation object to a list or automatically connect in the body of **printerDiscovered** when a certain printer is found. Now, users can also get notified when discovery starts and stops.

- **connectToDiscoveredPrinter** now takes a **DiscoveredPrinterInformation** object as a parameter now instead of just a String of the printer’s name. Since the only way to retrieve a **DiscoveredPrinterInformation** object is through the **printerDiscovered** method, this verifies that the object has already been discovered before a user tries to connect to it.

- **getLastConnectedPrinterName** replaced with **getLastConnectedPrinter** because it now returns a printer object rather than just the name as a String.

- **haveOwnership** is now called with a **PrinterDetails** object rather than a **PrinterDiscovery** object.


1.2.3

Includes the implementation of the M511 to the SDK. At this point, the M511 has the same functionalities as the M211. Therefore, collating and multiple labels templates are still not supported.

1.2.2

Includes a large improvement of printer connection efficiency and reliability thanks to our collaboration with ECSite.

1.2.1

Includes the implementation of automatic connection to a Bluetooth Low Energy.

1.2.0

This was the second major release of the Brady SDK that introduced support for the M211 Apollo printer and some added features such as:

- Disconnection/Forget a printer
- Feed a label
- Cut a label
- Set an M211's automatic shutoff time
- Improvements to how ownership is handled with an M211

1.1.0

This was the first release of the Brady SDK and the first time the Brady Android SDK was added to bradyid.com for public download. This version included a lot of the same functionality with some bug fixes to improve the speed and efficiency of its functionality.

1.0.0 (Beta)

This was the first version that was used internally with Brady employees to help test. This version included barebone functionality to discover, connect, and print templates.


