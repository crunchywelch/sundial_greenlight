//TODO: Change this to './bundle.js' when uploading to sdk.bradyid.com
import BradySdk from './bundle.pretty.js'

var statusLabel = document.getElementById('statusLabel')
const bradySdk = new BradySdk(printerUpdatesCallback, false) // second argument of 'false' means we will not collect analytics while developing

var imageToPrint

//THIS IS CODE TO DISCOVER AND CONNECT TO A PRINTER.
const bleScanButton = document.getElementById('startBleScanButton')
bleScanButton.addEventListener('click', async function(e) {
    const loader = document.querySelector(".spinner-displayer")
    loader.classList.add("loader")
    
    //DISPLAY CONNECTION STATUS.
    if (await bradySdk.showDiscoveredBleDevices()) {
        statusLabel.innerText = "Successfully Connected!"
        statusLabel.style.color = "green"
    }
    else {
        statusLabel.innerText = "Failed to connect..."
        statusLabel.style.color = "red"
    }

    loader.classList.remove("loader")
    printerUpdatesCallback(null)
})

const printBrowserButton = document.getElementById('printBrowserPageButton')
printBrowserButton.addEventListener('click', async function(e) {
    //TODO: Update this to 'https://sdk.bradyid.com/PrintPage.html' when uploading test app to sdk.bradyid.com
    location.href = "https://localhost:5500/BradyWebSdkTestApp/PrintPage.html"
})

//CODE TO FEED A LABEL
const feedButton = document.getElementById('feedButton')
feedButton.addEventListener('click', async function(e) {
    const loader = document.querySelector(".spinner-displayer")
    loader.classList.add("loader")

    const feedSuccessful = await bradySdk.feed()

    if(feedSuccessful) {
        statusLabel.innerText = "Feed Successful!"
        statusLabel.style.color = "green"
    }
    else {
        statusLabel.innerText = "Feed Failed..."
        statusLabel.style.color = "red"
    }

    loader.classList.remove("loader")
})

//CODE TO CUT A LABEL
const cutButton = document.getElementById('cutButton')
cutButton.addEventListener('click', async function(e) {
    const loader = document.querySelector(".spinner-displayer")
    loader.classList.add("loader")

    const feedSuccessful = await bradySdk.cut()

    if(feedSuccessful) {
        statusLabel.innerText = "Cut Successful!"
        statusLabel.style.color = "green"
    }
    else {
        statusLabel.innerText = "Cut Failed..."
        statusLabel.style.color = "red"
    }

    loader.classList.remove("loader")
})

//HANDLE THE PRINTER UPDATES
function printerUpdatesCallback(changedProperties) {
    statusLabel.style.color = "black"
    var detailsString = "";
    detailsString += "PrinterStatus:                         " + bradySdk.status + "\n";
    detailsString += "PrinterStatusMessage:                  " + bradySdk.message + "\n";
    detailsString += "PrinterStatusMessageTitle:             " + bradySdk.messageTitle + "\n";
    detailsString += "PrinterStatusRemedyExplanationMessage: " + bradySdk.messageRemedy + "\n";
    detailsString += "PrinterName:                           " + bradySdk.printerName + "\n";
    detailsString += "PrinterModel:                          " + bradySdk.printerModel + "\n";
    detailsString += "ConnectionType:                        " + "BLE" + "\n";
    detailsString += "BatteryLevelPercentage:                " + (bradySdk.batteryLevelPercentage == undefined ? "100%" : bradySdk.batteryLevelPercentage + "%") + "\n";
    detailsString += "Charging:                              " + bradySdk.isAcConnected + "\n";
    detailsString += "SupplyName:                            " + bradySdk.supplyName + "\n";
    detailsString += "SupplyYNumber:                         " + bradySdk.substrateYNumber + "\n";
    detailsString += "SupplyRemainingPercentage:             " + bradySdk.supplyRemainingPercentage + "%" + "\n";
    if (bradySdk.ribbonRemainingPercent) {
        detailsString += "RibbonRemainingPercentage:         " + bradySdk.ribbonRemainingPercent + "%" + "\n";
        }
    detailsString += "SupplyDimensions:                      " + bradySdk.supplyDimensions + "\n";
    detailsString += "SupplyWidth:                           " + bradySdk.substrateWidth + " inches" + "\n";
    detailsString += "SupplyHeight:                          " + bradySdk.substrateHeight + " inches" + "\n";
    detailsString += "SupplyIsDirectThermal:                 " + bradySdk.supplyIsDirectThermal + "\n";
    detailsString += "Dots Per Inch:                         " + bradySdk.dotsPerInch + "\n";
    detailsString += "Post Print Accessory:                  " + bradySdk.postPrintAccessoryType + "\n";
    detailsString += "IsSupplyPreSized:                      " + bradySdk.mediaIsDieCut + "\n";
    statusLabel.innerText = detailsString

    if (changedProperties != null) {
        if (changedProperties.length != 0) {
            console.log("Changed Properties:")
            for(var property in changedProperties) {
                console.log("....." + changedProperties[property])
            }
        }
    }

    if (!bradySdk.printerDiscovery.isConnected) {
        statusLabel.innerText = "Failed to connect..."
        statusLabel.style.color = "red"
    }

    if (!bradySdk.isSupportedBrowser()) {
        statusLabel.innerText = "This browser is not supported by the Web Bluetooth API."
        statusLabel.style.color = "red"
    }
}

//CODE TO PRINT THE SELECTED IMAGE.
const printBitmapButton = document.getElementById('printBitmapButton')
printBitmapButton.addEventListener('click', async function(e) {
    const loader = document.querySelector(".spinner-displayer")
    loader.classList.add("loader")

    const numCopies = document.getElementById('numCopies').value;
    if (numCopies && numCopies > 0) {
        bradySdk.setCopies(parseInt(numCopies))
    }

    const cutOptions = document.getElementById('cutOptions');
    const cutOption = cutOptions.value;
    if (cutOption === "EndOfJob") bradySdk.setCutOption(0);
    else if (cutOption === "EndOfLabel") bradySdk.setCutOption(1);
    else if (cutOption === "Never") bradySdk.setCutOption(2);
    else if (cutOption == "CutAfterRow") bradySdk.setCutOption(3);
    else if (cutOption == "UsePrinterSettings") bradySdk.setCutOption(4);

    let cutAfterRowOption = parseInt(document.getElementById("cutAfterRowOption").value);
    if (cutAfterRowOption) {
        bradySdk.setCutAfterRowValue(cutAfterRowOption)
    }

    const printingStatus = await bradySdk.printBitmap(imageToPrint)
    if(printingStatus) {
        statusLabel.innerText = "Printed Succesfully!"
        statusLabel.style.color = "green"
    }
    else {
        statusLabel.innerText = "Failed to print..."
        statusLabel.style.color = "red"
    }

    loader.classList.remove("loader")
})

//DISCONNECT FROM PRINTER FUNCTIONALITY
const disconnectButton = document.getElementById('disconnectButton')
disconnectButton.addEventListener('click', async function(e) {
    const disconnectStatus = await bradySdk.disconnect()
    if (disconnectStatus) {
        statusLabel.innerText = "Disconnected Successfully!"
        statusLabel.style.color = "green"
    }
    else {
        statusLabel.innerText = "Disconnect Failed..."
        statusLabel.style.color = "red"
    }
})

//CODE TO SELECT AND DISPLAY IMAGE TO PRINT.
const input = document.querySelector("input")
const preview = document.querySelector(".preview")
input.addEventListener("change", updateImageDisplay)
function updateImageDisplay() {
    while (preview.firstChild) {
        preview.removeChild(preview.firstChild)
    }

    const curFiles = input.files
    if (curFiles.length === 0) {
        const para = document.createElement("p")
        para.textContent = "No files currently selected for upload";
        preview.appendChild(para)
    } else {
        const list = document.createElement("ol")
        preview.appendChild(list)

        for (const file of curFiles) {
            const listItem = document.createElement("li")
            const para = document.createElement("p")
            if (validFileType(file)) {

                imageToPrint = document.createElement("img")
                imageToPrint.src = URL.createObjectURL(file)
                localStorage.setItem("imageToPrint", imageToPrint.src)

                //SHOWS THE IMAGE ON THE FRONT-END.
                listItem.appendChild(imageToPrint)

            } else {
                para.textContent = `File name ${file.name}: Not a valid file type. Update your selection.`
                listItem.appendChild(para)
            }

            list.appendChild(listItem)
        }
    }
}

window.toggleCutAfterRowOption = function toggleCutAfterRowOption() {
    const cutOptions = document.getElementById("cutOptions").value;
    const cutAfterRowContainer = document.getElementById("cutAfterRowContainer");

    if (cutOptions === "CutAfterRow") {
        cutAfterRowContainer.style.display = "block";
    } else {
        cutAfterRowContainer.style.display = "none";
    }
};

const fileTypes = [
  "image/apng",
  "image/bmp",
  "image/gif",
  "image/jpeg",
  "image/pjpeg",
  "image/png",
  "image/svg+xml",
  "image/tiff",
  "image/webp",
  "image/x-icon",
];

function validFileType(file) {
    return fileTypes.includes(file.type)
}
