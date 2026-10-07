"""Pure bounded CSV and create-only row/report contracts; SQL is forbidden."""

import csv
from io import StringIO
from itertools import permutations
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from apps.catalog.imports import (
    MAX_ERRORS,
    MAX_FILE_BYTES,
    MAX_PREVIEW,
    MAX_RECORDS,
    ImportStructureError,
    ImportUploadTooLarge,
    parse_catalogue_csv,
)
from apps.catalog.models import CatalogItem
from apps.catalog.serializers import CatalogItemCreateSerializer


def csv_bytes(rows, *, header=("sku", "description", "is_active"), newline="\r\n"):
    stream = StringIO(newline="")
    writer = csv.writer(stream, lineterminator=newline)
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


class CatalogImportContractTests(SimpleTestCase):
    def test_exact_headers_are_accepted_in_every_order(self):
        values = {"sku": " PART-001 ", "description": "Part", "is_active": "false"}
        for header in permutations(values):
            with self.subTest(header=header):
                parsed = parse_catalogue_csv(
                    csv_bytes([[values[key] for key in header]], header=header)
                )
                self.assertEqual(
                    parsed.rows[0].data,
                    {"sku": "PART-001", "description": "Part", "is_active": False},
                )

    def test_creation_normalization_and_defaults_are_reused_without_sql(self):
        source = {"sku": " \t000Ab/P-1.x  ", "description": " \tPart\n "}
        serializer = CatalogItemCreateSerializer(data=source)
        self.assertTrue(serializer.is_valid())
        parsed = parse_catalogue_csv(
            csv_bytes([[source["sku"], source["description"], ""]])
        )
        self.assertEqual(parsed.rows[0].data, serializer.validated_data)
        self.assertEqual(parsed.skus, {"000Ab/P-1.x"})
        report = parsed.report(set())
        self.assertEqual(
            set(report),
            {
                "dry_run",
                "mode",
                "can_import",
                "summary",
                "errors",
                "errors_truncated",
                "preview",
                "preview_truncated",
            },
        )
        self.assertIs(report["dry_run"], True)
        self.assertEqual(report["mode"], "create_only")
        self.assertIs(report["can_import"], True)
        self.assertEqual(
            report["preview"], [{"row_number": 2, **serializer.validated_data}]
        )

    def test_utf8_unicode_and_optional_bom_are_supported(self):
        raw = csv_bytes([["ÉCROU-東京", "Pièce métallique", "true"]])
        for prefix in (b"", b"\xef\xbb\xbf"):
            with self.subTest(prefix=prefix):
                row = parse_catalogue_csv(prefix + raw).rows[0]
                self.assertEqual(row.data["sku"], "ÉCROU-東京")
                self.assertEqual(row.data["description"], "Pièce métallique")

    def test_invalid_utf8_and_other_encodings_are_structural_errors(self):
        for raw in (
            b"\xff",
            b"\xed\xa0\x80",
            "sku,description,is_active\nA,,\n".encode("utf-16"),
        ):
            with (
                self.subTest(raw=raw[:4]),
                self.assertRaises(ImportStructureError) as error,
            ):
                parse_catalogue_csv(raw)
            self.assertEqual(error.exception.status_code, 400)
            self.assertEqual(
                str(error.exception.detail["detail"]), "Upload a valid UTF-8 CSV file."
            )

    def test_empty_file_bom_only_header_only_and_blank_records_are_rejected(self):
        for raw in (b"", b"\xef\xbb\xbf", csv_bytes([]), csv_bytes([[], []])):
            with self.subTest(raw=raw), self.assertRaises(ImportStructureError):
                parse_catalogue_csv(raw)

    def test_missing_duplicate_blank_unexpected_and_case_changed_headers_fail(self):
        headers = (
            (),
            ("sku", "description"),
            ("sku", "description", "sku"),
            ("sku", "description", ""),
            ("sku", "description", "extra"),
            ("Sku", "description", "is_active"),
            ("sku ", "description", "is_active"),
            ("sku", "description", "is_active", "organization_id"),
        )
        for header in headers:
            with (
                self.subTest(header=header),
                self.assertRaises(ImportStructureError) as error,
            ):
                parse_catalogue_csv(csv_bytes([["A", "", ""]], header=header))
            self.assertEqual(error.exception.detail["row_number"], 1)
            self.assertIsInstance(error.exception.detail["row_number"], int)

    def test_lf_and_crlf_records_are_supported(self):
        for newline in ("\n", "\r\n"):
            with self.subTest(newline=newline):
                parsed = parse_catalogue_csv(
                    csv_bytes([["A", "Part", ""]], newline=newline)
                )
                self.assertEqual(parsed.rows[0].data["description"], "Part")

    def test_quoted_commas_escaped_quotes_and_multiline_whitespace_are_preserved(self):
        description = '  Washer, "heavy duty"\r\nsecond line\n third line \t'
        row = parse_catalogue_csv(csv_bytes([["A", description, "true"]])).rows[0]
        self.assertEqual(row.data["description"], description)

    def test_row_numbers_count_logical_records_including_skipped_blank_records(self):
        raw = csv_bytes([["A", "first\nsecond\nthird", ""], [], ["B", "", "false"]])
        parsed = parse_catalogue_csv(raw)
        self.assertEqual([row.row_number for row in parsed.rows], [2, 4])
        self.assertEqual(
            [row["row_number"] for row in parsed.report(set())["preview"]], [2, 4]
        )

    def test_empty_values_record_remains_a_data_row_and_is_validated(self):
        parsed = parse_catalogue_csv(csv_bytes([[], ["", "", ""], []]))
        report = parsed.report(set())
        self.assertEqual(
            report["summary"], {"rows_total": 1, "rows_ready": 0, "rows_invalid": 1}
        )
        self.assertEqual(report["errors"][0]["row_number"], 3)
        self.assertEqual(report["errors"][0]["field"], "sku")
        self.assertFalse(report["can_import"])

    def test_wrong_column_counts_reject_the_entire_file_with_logical_location(self):
        for cells in (["A"], ["A", "description"], ["A", "", "", "extra"]):
            with (
                self.subTest(cells=cells),
                self.assertRaises(ImportStructureError) as error,
            ):
                parse_catalogue_csv(csv_bytes([["GOOD", "", ""], cells]))
            self.assertEqual(error.exception.detail["row_number"], 3)

    def test_unterminated_quotes_and_text_after_closing_quote_are_structural_errors(
        self,
    ):
        for record in (b'A,"unterminated,true\n', b'A,"quoted"junk,true\n'):
            with (
                self.subTest(record=record),
                self.assertRaises(ImportStructureError) as error,
            ):
                parse_catalogue_csv(b"sku,description,is_active\n" + record)
            self.assertEqual(error.exception.detail["row_number"], 2)

    def test_exact_record_limit_validates_the_whole_file(self):
        parsed = parse_catalogue_csv(
            csv_bytes([[f"A-{i}", "", ""] for i in range(MAX_RECORDS)])
        )
        report = parsed.report(set())
        self.assertEqual(
            report["summary"],
            {"rows_total": MAX_RECORDS, "rows_ready": MAX_RECORDS, "rows_invalid": 0},
        )
        self.assertTrue(report["can_import"])
        self.assertEqual(len(report["preview"]), MAX_PREVIEW)
        self.assertTrue(report["preview_truncated"])

    def test_record_limit_rejects_successful_partial_validation(self):
        with self.assertRaises(ImportStructureError) as error:
            parse_catalogue_csv(
                csv_bytes([[f"A-{i}", "", ""] for i in range(MAX_RECORDS + 1)])
            )
        self.assertEqual(error.exception.detail["row_number"], MAX_RECORDS + 2)

    def test_skipped_empty_records_do_not_consume_the_data_record_limit(self):
        rows = []
        for index in range(MAX_RECORDS):
            rows.extend([[f"A-{index}", "", ""], []])
        parsed = parse_catalogue_csv(csv_bytes(rows))
        self.assertEqual(len(parsed.rows), MAX_RECORDS)
        self.assertEqual(parsed.rows[-1].row_number, 2 * MAX_RECORDS)

    def test_oversized_bytes_are_rejected_before_invalid_encoding_is_decoded(self):
        with self.assertRaises(ImportUploadTooLarge) as error:
            parse_catalogue_csv(b"\xff" * (MAX_FILE_BYTES + 1))
        self.assertEqual(error.exception.status_code, 413)

    def test_exact_one_mib_of_valid_csv_is_accepted(self):
        row_count = 16
        rows = [[f"A-{index}", "", ""] for index in range(row_count)]
        available = MAX_FILE_BYTES - len(csv_bytes(rows))
        width, remainder = divmod(available, row_count)
        for index, row in enumerate(rows):
            row[1] = "x" * (width + (index < remainder))
        raw = csv_bytes(rows)
        self.assertEqual(len(raw), MAX_FILE_BYTES)
        report = parse_catalogue_csv(raw).report(set())
        self.assertTrue(report["can_import"])
        self.assertEqual(report["summary"]["rows_ready"], row_count)

    def test_native_csv_field_limit_is_respected_without_process_global_mutation(self):
        limit = csv.field_size_limit()
        self.assertLess(limit, MAX_FILE_BYTES)
        with self.assertRaises(ImportStructureError) as error:
            parse_catalogue_csv(csv_bytes([["A", "x" * (limit + 1), ""]]))
        self.assertEqual(error.exception.detail["row_number"], 2)
        self.assertEqual(csv.field_size_limit(), limit)
        parse_catalogue_csv(csv_bytes([["B", "normal", ""]]))
        self.assertEqual(csv.field_size_limit(), limit)

    def test_csv_booleans_accept_true_false_or_creation_default(self):
        parsed = parse_catalogue_csv(
            csv_bytes([["A", "", "true"], ["B", "", "false"], ["C", "", ""]])
        )
        expected = [True, False, CatalogItem._meta.get_field("is_active").get_default()]
        self.assertEqual([row.data["is_active"] for row in parsed.rows], expected)

    def test_other_boolean_spellings_numbers_and_whitespace_are_row_errors(self):
        for value in ("TRUE", "False", "1", "0", " true", "false ", " "):
            with self.subTest(value=value):
                row = parse_catalogue_csv(csv_bytes([["A", "", value]])).rows[0]
                self.assertIsNone(row.data)
                self.assertEqual(row.sku, "A")
                self.assertEqual(row.errors[0]["field"], "is_active")
                self.assertEqual(row.errors[0]["code"], "invalid_value")

    def test_empty_or_whitespace_sku_is_an_invalid_row(self):
        for value in ("", " \t\n"):
            with self.subTest(value=value):
                row = parse_catalogue_csv(csv_bytes([[value, "", ""]])).rows[0]
                self.assertIsNone(row.sku)
                self.assertIsNone(row.data)
                self.assertEqual(row.errors[0]["field"], "sku")

    def test_model_text_fields_keep_their_actual_unbounded_length_contract(self):
        for field in ("sku", "description"):
            self.assertIsNone(CatalogItem._meta.get_field(field).max_length)
        parsed = parse_catalogue_csv(csv_bytes([["A" * 5000, "D" * 6000, ""]]))
        self.assertEqual(len(parsed.rows[0].data["sku"]), 5000)
        self.assertEqual(len(parsed.rows[0].data["description"]), 6000)

    def test_nul_in_each_text_field_is_a_pure_row_error(self):
        for sku, description, field in (
            ("A\x00", "", "sku"),
            ("A", "D\x00", "description"),
        ):
            with self.subTest(field=field):
                row = parse_catalogue_csv(csv_bytes([[sku, description, ""]])).rows[0]
                self.assertIsNone(row.data)
                self.assertEqual(row.errors[0]["field"], field)

    def test_every_normalized_duplicate_occurrence_is_invalid_including_first(self):
        parsed = parse_catalogue_csv(
            csv_bytes([[" A ", "", ""], ["A", "", ""], ["a", "", ""]])
        )
        report = parsed.report(set())
        self.assertEqual(
            report["summary"], {"rows_total": 3, "rows_ready": 1, "rows_invalid": 2}
        )
        self.assertEqual([error["row_number"] for error in report["errors"]], [2, 3])
        self.assertTrue(
            all(error["code"] == "duplicate_file_sku" for error in report["errors"])
        )
        self.assertEqual([row["sku"] for row in report["preview"]], ["a"])
        self.assertIsNone(parsed.rows[0].data)

    def test_duplicate_sku_in_invalid_row_also_invalidates_valid_occurrence(
        self,
    ):
        for description, active in (("D\x00", ""), ("", "invalid")):
            with self.subTest(description=repr(description), active=active):
                parsed = parse_catalogue_csv(
                    csv_bytes([[" A ", description, active], ["A", "", ""]])
                )
                self.assertEqual(parsed.skus, {"A"})
                self.assertTrue(
                    all(
                        any(
                            error["code"] == "duplicate_file_sku"
                            for error in row.errors
                        )
                        for row in parsed.rows
                    )
                )
                self.assertEqual(parsed.report(set())["summary"]["rows_ready"], 0)

    def test_existing_skus_conflict_even_when_proposed_status_is_inactive(self):
        parsed = parse_catalogue_csv(
            csv_bytes([["A", "", "false"], ["B", "", "true"], ["C", "", ""]])
        )
        report = parsed.report({"A", "B"})
        self.assertEqual(
            report["summary"], {"rows_total": 3, "rows_ready": 1, "rows_invalid": 2}
        )
        self.assertTrue(
            all(error["code"] == "existing_workspace_sku" for error in report["errors"])
        )
        self.assertEqual(report["preview"][0]["sku"], "C")

    def test_existing_sku_matching_does_not_invent_case_folding(self):
        parsed = parse_catalogue_csv(csv_bytes([["a", "", ""]]))
        self.assertTrue(parsed.report({"A"})["can_import"])
        self.assertFalse(parsed.report({"a"})["can_import"])

    def test_reports_recheck_conflicts_without_mutating_parsed_rows(self):
        parsed = parse_catalogue_csv(csv_bytes([["A", "Description", ""]]))
        before = parsed.report(set())
        conflict = parsed.report({"A"})
        self.assertFalse(conflict["can_import"])
        self.assertEqual(parsed.rows[0].errors, [])
        self.assertEqual(parsed.report(set()), before)
        before["preview"][0]["description"] = "Caller change"
        self.assertEqual(parsed.rows[0].data["description"], "Description")

    def test_error_output_limit_does_not_truncate_validation_or_summary(self):
        parsed = parse_catalogue_csv(
            csv_bytes([["", "D\x00", "bad"] for _ in range(MAX_RECORDS)])
        )
        report = parsed.report(set())
        self.assertEqual(len(report["errors"]), MAX_ERRORS)
        self.assertTrue(report["errors_truncated"])
        self.assertFalse(report["can_import"])
        self.assertEqual(
            report["summary"],
            {"rows_total": MAX_RECORDS, "rows_ready": 0, "rows_invalid": MAX_RECORDS},
        )
        self.assertEqual(report["preview"], [])

    def test_exact_error_limit_is_not_marked_truncated(self):
        parsed = parse_catalogue_csv(
            csv_bytes([[f"A-{i}", "", "bad"] for i in range(MAX_ERRORS)])
        )
        report = parsed.report(set())
        self.assertEqual(len(report["errors"]), MAX_ERRORS)
        self.assertFalse(report["errors_truncated"])

    def test_preview_limit_does_not_hide_later_invalid_rows(self):
        rows = [[f"A-{i}", "", ""] for i in range(50)] + [["INVALID", "", "bad"]]
        report = parse_catalogue_csv(csv_bytes(rows)).report(set())
        self.assertEqual(len(report["preview"]), MAX_PREVIEW)
        self.assertTrue(report["preview_truncated"])
        self.assertFalse(report["can_import"])
        self.assertEqual(
            report["summary"], {"rows_total": 51, "rows_ready": 50, "rows_invalid": 1}
        )
        self.assertEqual(report["errors"][0]["row_number"], 52)

    def test_exact_preview_limit_is_not_marked_truncated(self):
        report = parse_catalogue_csv(
            csv_bytes([[f"A-{i}", "", ""] for i in range(MAX_PREVIEW)])
        ).report(set())
        self.assertEqual(len(report["preview"]), MAX_PREVIEW)
        self.assertFalse(report["preview_truncated"])

    def test_actual_model_field_validation_is_reused_and_error_messages_are_bounded(
        self,
    ):
        field = CatalogItem._meta.get_field("description")

        def reject(value):
            raise ValidationError("x" * 500)

        with patch.object(field, "validators", [*field.validators, reject]):
            row = parse_catalogue_csv(csv_bytes([["A", "description", ""]])).rows[0]
        self.assertIsNone(row.data)
        self.assertEqual(row.errors[0]["field"], "description")
        self.assertEqual(len(row.errors[0]["message"]), 200)

    def test_formula_looking_content_remains_plain_data(self):
        description = '=HYPERLINK("https://example.test", "text")'
        report = parse_catalogue_csv(
            csv_bytes([["=SUM(1+1)", description, ""]])
        ).report(set())
        self.assertEqual(report["preview"][0]["sku"], "=SUM(1+1)")
        self.assertEqual(report["preview"][0]["description"], description)
