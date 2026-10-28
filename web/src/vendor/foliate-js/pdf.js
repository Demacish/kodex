// Kodex: PDFs open in Kodex's own pdf.js reader (src/readers/pdf), so this
// stands in for foliate-js's pdf.js and its 13 MB bundled copy of pdf.js.
import { UnsupportedTypeError } from './view.js'

export const makePDF = async () => {
    throw new UnsupportedTypeError('PDF is read by the PDF reader')
}
