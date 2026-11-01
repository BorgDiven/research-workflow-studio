import base64
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch
import zlib

from rws.pdf_reading import generate_reading_pdf, pdf_converter_available


@unittest.skipUnless(pdf_converter_available(), 'optional pypdf/Pillow not installed')
class PDFReadingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='rws-pdf-reading-')
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def make_pdf(self, path, masked=False, nested=False):
        from pypdf import PdfWriter
        from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject,
                                  EncodedStreamObject, NameObject, NumberObject)
        writer = PdfWriter()
        page = writer.add_blank_page(width=720, height=540)
        pixels = random.Random(6).randbytes(600 * 400 * 3)

        def image_stream():
            image = EncodedStreamObject()
            image._data = base64.a85encode(zlib.compress(pixels), adobe=True)
            image.update({NameObject('/Type'): NameObject('/XObject'),
                          NameObject('/Subtype'): NameObject('/Image'),
                          NameObject('/Width'): NumberObject(600),
                          NameObject('/Height'): NumberObject(400),
                          NameObject('/ColorSpace'): NameObject('/DeviceRGB'),
                          NameObject('/BitsPerComponent'): NumberObject(8),
                          NameObject('/Filter'): ArrayObject([NameObject('/ASCII85Decode'), NameObject('/FlateDecode')])})
            return image

        image = image_stream()
        xobjects = DictionaryObject({NameObject('/Im0'): writer._add_object(image)})
        if masked:
            mask = DecodedStreamObject()
            mask.set_data(bytes([128]) * 600 * 400)
            mask.update({NameObject('/Type'): NameObject('/XObject'),
                         NameObject('/Subtype'): NameObject('/Image'),
                         NameObject('/Width'): NumberObject(600), NameObject('/Height'): NumberObject(400),
                         NameObject('/ColorSpace'): NameObject('/DeviceGray'),
                         NameObject('/BitsPerComponent'): NumberObject(8)})
            masked_image = image_stream()
            masked_image[NameObject('/SMask')] = writer._add_object(mask)
            xobjects[NameObject('/Im1')] = writer._add_object(masked_image)
        if nested:
            form = DecodedStreamObject()
            form.set_data(b'q 600 0 0 400 0 0 cm /Im0 Do Q')
            form.update({NameObject('/Type'): NameObject('/XObject'),
                         NameObject('/Subtype'): NameObject('/Form'),
                         NameObject('/BBox'): ArrayObject([NumberObject(n) for n in [0, 0, 600, 400]]),
                         NameObject('/Resources'): DictionaryObject({NameObject('/XObject'): xobjects})})
            xobjects = DictionaryObject({NameObject('/Fm0'): writer._add_object(form)})
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                 NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): xobjects,
            NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        content = DecodedStreamObject()
        image_command = b'/Fm0 Do /Fm0 Do' if nested else b'q 600 0 0 400 0 0 cm /Im0 Do Q'
        content.set_data(image_command + b'\nBT /F1 14 Tf 30 500 Td (Fixed evidence report) Tj ET\n0 0 100 100 re S')
        page[NameObject('/Contents')] = writer._add_object(content)
        writer.add_uri(0, 'https://example.org/fixed-evidence', [30, 490, 200, 520])
        writer.add_outline_item('Evidence', 0)
        writer.add_metadata({'/Title': 'Reading fixture'})
        with path.open('wb') as stream:
            writer.write(stream)

    def test_smaller_copy_preserves_text_geometry_vectors_links_and_source(self):
        from pypdf import PdfReader
        source, output = self.root / 'source.pdf', self.root / 'reading.pdf'
        self.make_pdf(source)
        original = source.read_bytes()
        receipt = generate_reading_pdf(source, output)
        self.assertEqual(source.read_bytes(), original)
        self.assertLess(output.stat().st_size, source.stat().st_size)
        self.assertEqual(receipt['recompressedImages'], 1)
        before, after = PdfReader(source), PdfReader(output)
        self.assertEqual(len(before.pages), len(after.pages))
        self.assertEqual(before.pages[0].extract_text(), after.pages[0].extract_text())
        self.assertEqual(before.pages[0].mediabox, after.pages[0].mediabox)
        self.assertEqual(before.pages[0].get_contents().get_data(), after.pages[0].get_contents().get_data())
        self.assertEqual(before.pages[0]['/Annots'][0].get_object()['/A']['/URI'],
                         after.pages[0]['/Annots'][0].get_object()['/A']['/URI'])
        self.assertEqual(before.outline[0]['/Title'], after.outline[0]['/Title'])
        self.assertEqual(before.metadata.title, after.metadata.title)
        image = after.pages[0]['/Resources']['/XObject']['/Im0']
        self.assertEqual(image['/Filter'], '/DCTDecode')
        self.assertEqual((image['/Width'], image['/Height']), (600, 400))
        self.assertEqual(after.pages[0].images[0].image.size, (600, 400))

    def test_masked_image_remains_untouched(self):
        from pypdf import PdfReader
        source, output = self.root / 'source.pdf', self.root / 'reading.pdf'
        self.make_pdf(source, masked=True)
        receipt = generate_reading_pdf(source, output)
        self.assertEqual(receipt['recompressedImages'], 1)
        self.assertEqual(receipt['skippedImages'], 1)
        before = PdfReader(source).pages[0]['/Resources']['/XObject']['/Im1']
        after = PdfReader(output).pages[0]['/Resources']['/XObject']['/Im1']
        self.assertEqual(before._data, after._data)
        self.assertEqual(before['/SMask']._data, after['/SMask']._data)

    def test_nested_shared_images_are_processed_once(self):
        source, output = self.root / 'source.pdf', self.root / 'reading.pdf'
        self.make_pdf(source, nested=True)
        self.assertEqual(generate_reading_pdf(source, output)['recompressedImages'], 1)

    def test_limits_and_converter_failures_never_overwrite_original(self):
        source, output = self.root / 'source.pdf', self.root / 'reading.pdf'
        self.make_pdf(source)
        original = source.read_bytes()
        with self.assertRaisesRegex(ValueError, 'differ'):
            generate_reading_pdf(source, source)
        with patch('rws.pdf_reading.MAX_SOURCE_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'input limit'):
                generate_reading_pdf(source, output)
        with patch('rws.pdf_reading.MAX_IMAGE_PIXELS', 1), patch('rws.pdf_reading.SMALL_PDF_MAX_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'no safely reducible'):
                generate_reading_pdf(source, output)
        with patch('rws.pdf_reading.pdf_converter_available', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'optional'):
                generate_reading_pdf(source, output)
        self.assertFalse(output.exists())
        self.assertEqual(source.read_bytes(), original)

    def test_oversized_decoded_image_is_skipped(self):
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import NameObject, NumberObject
        source, output = self.root / 'source.pdf', self.root / 'reading.pdf'
        self.make_pdf(source)
        writer = PdfWriter(clone_from=PdfReader(source))
        writer.pages[0]['/Resources']['/XObject']['/Im0'][NameObject('/Width')] = NumberObject(1)
        malformed = self.root / 'wrong-dimensions.pdf'
        with malformed.open('wb') as stream:
            writer.write(stream)
        with patch('rws.pdf_reading.SMALL_PDF_MAX_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'no safely reducible'):
                generate_reading_pdf(malformed, output)
        self.assertFalse(output.exists())

    def test_already_light_text_pdf_remains_readable_as_a_separate_copy(self):
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
        source, output = self.root / 'compact.pdf', self.root / 'reading.pdf'
        writer = PdfWriter()
        page = writer.add_blank_page(width=720, height=540)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                 NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
            DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        content = DecodedStreamObject()
        content.set_data(b'BT /F1 14 Tf 30 500 Td (Compact fixed report) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(content)
        with source.open('wb') as stream:
            writer.write(stream)
        original = source.read_bytes()
        receipt = generate_reading_pdf(source, output)
        self.assertEqual(source.read_bytes(), original)
        self.assertTrue(receipt['alreadyLightweight'])
        self.assertEqual(receipt['recompressedImages'], 0)
        self.assertLessEqual(output.stat().st_size, 8 * 1024 * 1024)
        self.assertEqual(PdfReader(output).pages[0].extract_text(), 'Compact fixed report')
        self.assertNotEqual(source.stat().st_ino, output.stat().st_ino)

    def make_inline_pdf(self, path):
        from pypdf import PdfWriter
        from pypdf.generic import (ArrayObject, DictionaryObject, EncodedStreamObject,
                                  NameObject)
        writer = PdfWriter()
        page = writer.add_blank_page(width=720, height=540)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                 NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
            DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        parts = [b'BT /F1 14 Tf 30 500 Td (Before inline images) Tj ET\n']
        for channels, color in ((3, b'/RGB'), (1, b'/G')):
            pixels = random.Random(channels).randbytes(600 * 400 * channels)
            # Include EI-like byte sequences in decoded pixels. Encoding and
            # parsing must use the actual image boundary, not a substring.
            pixels = b' EI Q BT (' + pixels[10:]
            encoded = base64.a85encode(zlib.compress(pixels)) + b'~>'
            parts.extend([b'q 600 0 0 400 0 0 cm\nBI /W 600 /H 400 /BPC 8 /CS ', color,
                          b' /F [/A85 /Fl] ID\n', encoded, b'\nEI\nQ\n'])
        parts.append(b'BT /F1 14 Tf 30 470 Td (After inline images) Tj ET\n0 0 100 100 re S\n')
        content = EncodedStreamObject()
        content._data = base64.a85encode(zlib.compress(b''.join(parts))) + b'~>'
        content[NameObject('/Filter')] = ArrayObject([NameObject('/ASCII85Decode'), NameObject('/FlateDecode')])
        page[NameObject('/Contents')] = writer._add_object(content)
        writer.add_uri(0, 'https://example.org/inline-evidence', [30, 460, 200, 490])
        with path.open('wb') as stream:
            writer.write(stream)

    def test_inline_rgb_and_gray_keep_nonimage_operations_text_links_and_dimensions(self):
        from pypdf import PdfReader
        source, output = self.root / 'inline.pdf', self.root / 'reading.pdf'
        self.make_inline_pdf(source)
        original = source.read_bytes()
        receipt = generate_reading_pdf(source, output)
        self.assertEqual(source.read_bytes(), original)
        self.assertLess(output.stat().st_size, source.stat().st_size)
        self.assertEqual(receipt['recompressedInlineImages'], 2)
        self.assertEqual(receipt['inlinePages'], 1)
        before, after = PdfReader(source), PdfReader(output)
        before_ops, after_ops = before.pages[0].get_contents().operations, after.pages[0].get_contents().operations
        self.assertEqual([item for item in before_ops if item[1] != b'INLINE IMAGE'],
                         [item for item in after_ops if item[1] != b'INLINE IMAGE'])
        self.assertEqual(before.pages[0].extract_text(), after.pages[0].extract_text())
        self.assertIn('After inline images', after.pages[0].extract_text())
        self.assertEqual(before.pages[0].mediabox, after.pages[0].mediabox)
        self.assertEqual(before.pages[0]['/Annots'][0].get_object()['/A']['/URI'],
                         after.pages[0]['/Annots'][0].get_object()['/A']['/URI'])
        images = [operands for operands, operator in after_ops if operator == b'INLINE IMAGE']
        self.assertEqual(len(images), 2)
        for image in images:
            self.assertEqual((image['settings']['/W'], image['settings']['/H']), (600, 400))
            self.assertEqual(image['settings']['/F'], ['/A85', '/DCT'])
        for image in after.pages[0].images:
            self.assertEqual(image.image.size, (600, 400))

    def test_inline_page_decode_limit_preserves_original_and_leaves_no_output(self):
        source, output = self.root / 'inline.pdf', self.root / 'reading.pdf'
        self.make_inline_pdf(source)
        original = source.read_bytes()
        with patch('rws.pdf_reading.MAX_PAGE_CONTENT_BYTES', 1024):
            with self.assertRaisesRegex(ValueError, 'page content exceeds'):
                generate_reading_pdf(source, output)
        self.assertEqual(source.read_bytes(), original)
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
