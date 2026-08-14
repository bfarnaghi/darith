/*
 * Author: Behnam <b.farnaghi@gmail.com>
 * AI-assisted implementation; manually reviewed and verified by the developer.
 */
/* messages.js */

// Function to hide messages after a certain time
function hideMessages() {
    setTimeout(function() {
        var messages = document.getElementsByClassName('message');
        for (var i = 0; i < messages.length; i++) {
            messages[i].style.display = 'none';
        }
    }, 10000); // Hide messages after 5 seconds (adjust as needed)
}

// Call hideMessages function when the document is loaded
document.addEventListener('DOMContentLoaded', hideMessages);
