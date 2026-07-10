var fs = require('fs');
var code = fs.readFileSync('D:/讲书升级Agent/web/static/app.js', 'utf-8');
var line = code.split('\n')[101];

// Try to parse just the string portions
var str = line.trim();
console.log('Line length:', str.length);

// Count non-escaped single quotes
var quotePositions = [];
for (var i = 0; i < str.length; i++) {
    // Check for non-escaped single quote
    if (str[i] === "'" && (i === 0 || str[i-1] !== '\\')) {
        quotePositions.push(i);
    }
}
console.log('Non-escaped single quotes found:', quotePositions.length);
console.log('Positions:', quotePositions.join(', '));

// With variables borderColor, bookName, kpId, and function encodeURIComponent
// the number should be even (start/end string boundaries)
if (quotePositions.length % 2 !== 0) {
    console.log('UNBALANCED quotes!');
} else {
    console.log('Balanced quotes (even number)');
}

// Check what's at the position right before the '&kp_id='
// The string '&kp_id=' should be a JS string literal
var qp = quotePositions;
for (var i = 0; i < qp.length; i += 2) {
    var chunk = str.substring(qp[i], qp[i+1] + 1);
    console.log('String chunk', i/2, ':', chunk.substring(0, 60), '...');
}
