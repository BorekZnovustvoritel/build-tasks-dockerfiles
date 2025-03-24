from unittest.mock import MagicMock, patch

import datetime
import pytest

import add_image_reference


def test_setup_arg_parser() -> None:
    parser = add_image_reference.setup_arg_parser()
    assert parser.description == "Add image reference to image SBOM."
    assert parser._option_string_actions["--image-url"].required
    assert parser._option_string_actions["--image-digest"].required


def test_Image() -> None:
    image = add_image_reference.Image.from_image_index_url_and_digest(
        "quay.io/namespace/repository/image:tag", "sha256:digest", False
    )

    assert image.repository == "quay.io/namespace/repository/image"
    assert image.name == "image"
    assert image.digest == "sha256:digest"
    assert image.tag == "tag"

    assert image.digest_algo_cyclonedx == "SHA-256"
    assert image.digest_algo_spdx == "SHA256"
    assert image.digest_hex_val == "digest"

    assert image.purl() == ("pkg:oci/image@sha256:digest?repository_url=quay.io/namespace/repository/image")


@pytest.mark.parametrize(
    "builder_image,components_count", [(True, 1), (False, 2)], ids=["build-image", "component-image"]
)
def test_update_component_in_cyclonedx_sbom(builder_image: bool, components_count: int) -> None:
    sbom = {"bomFormat": "CycloneDX", "metadata": {"component": {}}, "components": [{}]}
    image = add_image_reference.Image.from_image_index_url_and_digest(
        "quay.io/namespace/repository/image:tag",
        "sha256:digest",
        builder_image,
    )

    result = add_image_reference.update_component_in_cyclonedx_sbom(sbom=sbom, image=image)

    image_sbom = {
        "type": "container",
        "name": image.name,
        "purl": image.purl(),
        "version": image.tag,
        "hashes": [{"alg": image.digest_algo_cyclonedx, "content": image.digest_hex_val}],
    }

    if builder_image:
        location = result["formulation"][0]["components"][0]
        image_sbom_proterty = {
            "name": "konflux:container:is_builder_image:additional_builder_image",
            "value": "script-runner-image",
        }
        image_sbom["properties"] = [image_sbom_proterty]
        assert location
    else:
        location = result["components"][0]
        assert (
            result["metadata"]["component"]["purl"]
            == "pkg:oci/image@sha256:digest?repository_url=quay.io/namespace/repository/image"
        )
    assert len(result["components"]) == components_count

    assert location == image_sbom
    assert result["metadata"]["component"] == result["components"][0]


def test_find_package_by_spdx_id() -> None:
    sbom = {"packages": [{"SPDXID": "foo"}, {"SPDXID": "bar"}]}
    assert add_image_reference.find_package_by_spdx_id(sbom, "foo") == {"SPDXID": "foo"}
    assert add_image_reference.find_package_by_spdx_id(sbom, "baz") is None


def test_delete_package_by_spdx_id() -> None:
    sbom = {"packages": [{"SPDXID": "foo"}, {"SPDXID": "bar"}]}
    add_image_reference.delete_package_by_spdx_id(sbom, "foo")
    assert sbom["packages"] == [{"SPDXID": "bar"}]


def test_redirect_virtual_root_to_new_root() -> None:
    sbom = {
        "relationships": [
            {"spdxElementId": "foo", "relationshipType": "DESCRIBES", "relatedSpdxElement": "bar"},
            {"spdxElementId": "bar", "relationshipType": "DESCRIBES", "relatedSpdxElement": "baz"},
            {"spdxElementId": "baz", "relationshipType": "DESCRIBES", "relatedSpdxElement": "qux"},
        ]
    }
    add_image_reference.redirect_virtual_root_to_new_root(sbom, "bar", "qux")

    assert sbom["relationships"] == [
        {"spdxElementId": "foo", "relationshipType": "DESCRIBES", "relatedSpdxElement": "qux"},
        {"spdxElementId": "qux", "relationshipType": "DESCRIBES", "relatedSpdxElement": "baz"},
        {"spdxElementId": "baz", "relationshipType": "DESCRIBES", "relatedSpdxElement": "qux"},
    ]


def test_delete_relationship_by_related_spdx_id() -> None:
    sbom = {
        "relationships": [
            {"spdxElementId": "foo", "relationshipType": "DESCRIBES", "relatedSpdxElement": "bar"},
            {"spdxElementId": "bar", "relationshipType": "DESCRIBES", "relatedSpdxElement": "baz"},
            {"spdxElementId": "baz", "relationshipType": "DESCRIBES", "relatedSpdxElement": "qux"},
        ]
    }
    add_image_reference.delete_relationship_by_related_spdx_id(sbom, "baz")

    assert sbom["relationships"] == [
        {"spdxElementId": "foo", "relationshipType": "DESCRIBES", "relatedSpdxElement": "bar"},
        {"spdxElementId": "baz", "relationshipType": "DESCRIBES", "relatedSpdxElement": "qux"},
    ]


def test_describes_the_document() -> None:
    relationship = {
        "spdxElementId": "SPDXRef-DOCUMENT",
        "relationshipType": "DESCRIBES",
        "relatedSpdxElement": "SPDXRef-image",
    }

    assert add_image_reference.describes_the_document(relationship, "SPDXRef-DOCUMENT") is True

    relationship["spdxElementId"] = "foo"

    assert add_image_reference.describes_the_document(relationship, "SPDXRef-DOCUMENT") is False


def test_is_virtual_root() -> None:
    package = {"SPDXID": "foo", "name": ""}

    assert add_image_reference.is_virtual_root(package) is True

    package["name"] = "./some-dir"
    assert add_image_reference.is_virtual_root(package) is True

    package["name"] = "/some/absolute/path"
    assert add_image_reference.is_virtual_root(package) is True

    package["name"] = "bar"
    assert add_image_reference.is_virtual_root(package) is False


def test_redirect_current_roots_to_new_root() -> None:
    # Replacing a virtual root with a new root
    sbom = {
        "packages": [
            {"SPDXID": "virtual", "name": ""},
            {"SPDXID": "virtual2", "name": "./some-dir"},
            {"SPDXID": "bar", "name": "bar"},
            {"SPDXID": "baz", "name": "baz"},
            {"SPDXID": "spam", "name": "spam"},
        ],
        "relationships": [
            {"spdxElementId": "foo", "relationshipType": "DESCRIBES", "relatedSpdxElement": "virtual"},
            {"spdxElementId": "foo", "relationshipType": "DESCRIBES", "relatedSpdxElement": "virtual2"},
            {"spdxElementId": "virtual", "relationshipType": "CONTAINS", "relatedSpdxElement": "baz"},
            {"spdxElementId": "virtual2", "relationshipType": "CONTAINS", "relatedSpdxElement": "spam"},
        ],
        "SPDXID": "foo",
    }
    result = add_image_reference.redirect_current_roots_to_new_root(sbom, "bar")

    assert result == {
        "packages": [
            {"SPDXID": "bar", "name": "bar"},
            {"SPDXID": "baz", "name": "baz"},
            {"SPDXID": "spam", "name": "spam"},
        ],
        "relationships": [
            {"spdxElementId": "bar", "relationshipType": "CONTAINS", "relatedSpdxElement": "baz"},
            {"spdxElementId": "bar", "relationshipType": "CONTAINS", "relatedSpdxElement": "spam"},
        ],
        "SPDXID": "foo",
    }

    # Replacing a root with a new root and redirecting the old root to the new root
    sbom = {
        "packages": [
            {"SPDXID": "npm", "name": "npm"},
            {"SPDXID": "bar", "name": "bar"},
            {"SPDXID": "baz", "name": "baz"},
            {"SPDXID": "pip", "name": "pip"},
            {"SPDXID": "spam", "name": "spam"},
        ],
        "relationships": [
            {"spdxElementId": "foo", "relationshipType": "DESCRIBES", "relatedSpdxElement": "npm"},
            {"spdxElementId": "foo", "relationshipType": "DESCRIBES", "relatedSpdxElement": "pip"},
            {"spdxElementId": "npm", "relationshipType": "CONTAINS", "relatedSpdxElement": "baz"},
            {"spdxElementId": "pip", "relationshipType": "CONTAINS", "relatedSpdxElement": "spam"},
        ],
        "SPDXID": "foo",
    }
    result = add_image_reference.redirect_current_roots_to_new_root(sbom, "bar")

    assert result == {
        "packages": [
            {"SPDXID": "npm", "name": "npm"},
            {"SPDXID": "bar", "name": "bar"},
            {"SPDXID": "baz", "name": "baz"},
            {"SPDXID": "pip", "name": "pip"},
            {"SPDXID": "spam", "name": "spam"},
        ],
        "relationships": [
            {"spdxElementId": "bar", "relationshipType": "CONTAINS", "relatedSpdxElement": "npm"},
            {"spdxElementId": "bar", "relationshipType": "CONTAINS", "relatedSpdxElement": "pip"},
            {"spdxElementId": "npm", "relationshipType": "CONTAINS", "relatedSpdxElement": "baz"},
            {"spdxElementId": "pip", "relationshipType": "CONTAINS", "relatedSpdxElement": "spam"},
        ],
        "SPDXID": "foo",
    }


@pytest.mark.parametrize(
    "sbom,expected_output",
    [
        # SPDX with no root package
        (
            {
                "SPDXID": "SPDXRef-Document",
                "spdxVersion": "SPDX-2.3",
                "name": "MyProject",
                "documentNamespace": "http://example.com/uid-1234",
            },
            ValueError(r"Found 0 ROOTs: \[\]"),
        ),
        # SPDX with too many roots
        (
            {
                "SPDXID": "SPDXRef-Document",
                "spdxVersion": "SPDX-2.3",
                "name": "MyProject",
                "documentNamespace": "http://example.com/uid-1234",
                "packages": [
                    {
                        "SPDXID": "SPDXRef-root1",
                        "name": "",
                        "downloadLocation": "NOASSERTION",
                    },
                    {
                        "SPDXID": "SPDXRef-root2",
                        "name": "",
                        "downloadLocation": "NOASSERTION",
                    },
                ],
                "relationships": [
                    {
                        "spdxElementId": "SPDXRef-Document",
                        "relationshipType": "DESCRIBES",
                        "relatedSpdxElement": "SPDXRef-root1",
                    },
                    {
                        "spdxElementId": "SPDXRef-Document",
                        "relationshipType": "DESCRIBES",
                        "relatedSpdxElement": "SPDXRef-root2",
                    },
                ],
            },
            ValueError(r"Found 2 ROOTs: \['SPDXRef-root1', 'SPDXRef-root2'\]"),
        ),
        # minimal valid SPDX SBOM
        (
            {
                "SPDXID": "SPDXRef-Document",
                "spdxVersion": "SPDX-2.3",
                "name": "MyProject",
                "documentNamespace": "http://example.com/uid-1234",
                "packages": [
                    {
                        "SPDXID": "SPDXRef-image-my-cool-image",
                        "name": "MyMainPackage",
                        "downloadLocation": "NOASSERTION",
                    },
                ],
                "relationships": [
                    {
                        "spdxElementId": "SPDXRef-Document",
                        "relationshipType": "DESCRIBES",
                        "relatedSpdxElement": "SPDXRef-image-my-cool-image",
                    },
                ],
            },
            "SPDXRef-image-my-cool-image",
        ),
    ],
)
def test_find_spdx_root_package(sbom, expected_output) -> None:
    if not isinstance(expected_output, Exception):
        assert add_image_reference.find_spdx_root_package(sbom) == expected_output
    else:
        with pytest.raises(type(expected_output), match=str(expected_output)):
            add_image_reference.find_spdx_root_package(sbom)


@patch("add_image_reference.redirect_current_roots_to_new_root")
def test_update_package_in_spdx_sbom(mock_root_redicret: MagicMock) -> None:
    sbom = {"spdxVersion": "1.1.1", "SPDXID": "foo", "packages": [{}], "relationships": []}
    image = add_image_reference.Image.from_image_index_url_and_digest(
        "quay.io/namespace/repository/image:tag", "sha256:digest", False
    )

    result = add_image_reference.update_package_in_spdx_sbom(sbom=sbom, image=image)

    assert len(result["packages"]) == 2
    assert result["packages"][0] == {
        "SPDXID": "SPDXRef-image",
        "name": image.name,
        "versionInfo": image.tag,
        "downloadLocation": "NOASSERTION",
        "licenseConcluded": "NOASSERTION",
        "supplier": "NOASSERTION",
        "externalRefs": [
            {
                "referenceLocator": image.purl(),
                "referenceType": "purl",
                "referenceCategory": "PACKAGE-MANAGER",
            }
        ],
        "checksums": [{"algorithm": image.digest_algo_spdx, "checksumValue": image.digest_hex_val}],
    }

    assert len(result["relationships"]) == 1
    assert result["relationships"][0] == {
        "spdxElementId": sbom["SPDXID"],
        "relationshipType": "DESCRIBES",
        "relatedSpdxElement": "SPDXRef-image",
    }

    mock_root_redicret.assert_called_once_with(sbom, "SPDXRef-image")


@patch("add_image_reference._datetime_utc_now", return_value=datetime.datetime(2025, 3, 12))
def test_update_package_in_spdx_sbom_builder_image(mock_dt) -> None:
    sbom = {
        "SPDXID": "SPDXRef-Document",
        "spdxVersion": "SPDX-2.3",
        "name": "MyProject",
        "documentNamespace": "http://example.com/uid-1234",
        "packages": [
            {
                "SPDXID": "SPDXRef-image-my-cool-image",
                "name": "MyMainPackage",
                "downloadLocation": "NOASSERTION",
            },
        ],
        "relationships": [
            {
                "spdxElementId": "SPDXRef-Document",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": "SPDXRef-image-my-cool-image",
            },
        ],
    }
    image = add_image_reference.Image.from_image_index_url_and_digest(
        "quay.io/namespace/repository/image:tag", "sha256:digest", True
    )

    result = add_image_reference.update_package_in_spdx_sbom(sbom=sbom, image=image)

    assert len(result["packages"]) == 2
    assert result["packages"][1] == {
        "SPDXID": image.spdx_id,
        "name": image.name,
        "versionInfo": image.tag,
        "downloadLocation": "NOASSERTION",
        "licenseConcluded": "NOASSERTION",
        "supplier": "NOASSERTION",
        "externalRefs": [
            {
                "referenceLocator": image.purl(),
                "referenceType": "purl",
                "referenceCategory": "PACKAGE-MANAGER",
            }
        ],
        "checksums": [{"algorithm": image.digest_algo_spdx, "checksumValue": image.digest_hex_val}],
        "annotations": [
            {
                "annotationDate": "2025-03-12T00:00:00Z",
                "annotationType": "OTHER",
                "annotator": "Tool: konflux:jsonencoded",
                "comment": '{"name":"konflux:container:is_builder_image:additional_builder_image","value":"script-runner-image"}',  # noqa: E501
            }
        ],
    }

    assert len(result["relationships"]) == 2
    assert result["relationships"][1] == {
        "spdxElementId": image.spdx_id,
        "relationshipType": "BUILD_TOOL_OF",
        "relatedSpdxElement": "SPDXRef-image-my-cool-image",
    }


@patch("add_image_reference.update_package_in_spdx_sbom")
@patch("add_image_reference.update_component_in_cyclonedx_sbom")
def test_extend_sbom_with_image_reference(cyclonedx_update: MagicMock, spdx_update: MagicMock) -> None:
    sbom = {"bomFormat": "CycloneDX"}
    image = MagicMock()
    add_image_reference.extend_sbom_with_image_reference(sbom, image)

    cyclonedx_update.assert_called_once_with(sbom, image)
    spdx_update.assert_not_called()

    cyclonedx_update.reset_mock()
    spdx_update.reset_mock()

    sbom = {"spdxVersion": "1.1.1"}
    add_image_reference.extend_sbom_with_image_reference(sbom, image)

    cyclonedx_update.assert_not_called()
    spdx_update.assert_called_once_with(sbom, image)


def test_update_name() -> None:
    image = add_image_reference.Image.from_image_index_url_and_digest(
        "quay.io/namespace/repository/image:tag", "sha256:digest", False
    )

    result = add_image_reference.update_name({"spdxVersion": "1.1.1"}, image)
    assert result["name"] == "quay.io/namespace/repository/image@sha256:digest"


@patch("json.dump")
@patch("json.load")
@patch("add_image_reference.update_name")
@patch("add_image_reference.extend_sbom_with_image_reference")
@patch(
    "add_image_reference.Image.from_image_index_url_and_digest",
    return_value=add_image_reference.Image(
        "quay.io/namespace/repository/image", "image", "sha256:digest", "latest", False
    ),
)
@patch("builtins.open")
@patch("add_image_reference.setup_arg_parser")
def test_main(
    mock_parser: MagicMock,
    mock_open: MagicMock,
    mock_image: MagicMock,
    mock_extend_sbom: MagicMock,
    mock_name: MagicMock,
    mock_load: MagicMock,
    mock_dump: MagicMock,
) -> None:
    add_image_reference.main()

    mock_parser.assert_called_once()
    mock_parser.return_value.parse_args.assert_called_once()
    mock_image.assert_called_once()
    assert mock_open.call_count == 2

    mock_load.assert_called_once()
    mock_extend_sbom.assert_called_once()
    mock_name.assert_called_once()
    mock_dump.assert_called_once()


@patch("json.dump")
@patch("json.load")
@patch("add_image_reference.update_name")
@patch("add_image_reference.extend_sbom_with_image_reference")
@patch(
    "add_image_reference.Image.from_image_index_url_and_digest",
    return_value=add_image_reference.Image(
        "quay.io/namespace/repository/image", "image", "sha256:digest", "latest", True
    ),
)
@patch("builtins.open")
@patch("add_image_reference.setup_arg_parser")
def test_main_builder_image(
    mock_parser: MagicMock,
    mock_open: MagicMock,
    mock_image: MagicMock,
    mock_extend_sbom: MagicMock,
    mock_name: MagicMock,
    mock_load: MagicMock,
    mock_dump: MagicMock,
) -> None:
    add_image_reference.main()

    mock_parser.assert_called_once()
    mock_parser.return_value.parse_args.assert_called_once()
    mock_image.assert_called_once()
    assert mock_open.call_count == 2

    mock_load.assert_called_once()
    mock_extend_sbom.assert_called_once()
    mock_name.assert_not_called()
    mock_dump.assert_called_once()
