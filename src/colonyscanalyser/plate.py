from __future__ import annotations
from typing import Union, Dict, List, Tuple
from collections.abc import Collection
from pathlib import Path, PurePath
from numpy import ndarray
from .base import Identified, IdentifiedCollection, Named
from .geometry import Circle
from .file_access import save_to_csv


class Plate(Identified, IdentifiedCollection, Named, Circle):
    """
    An object to hold information about an agar plate and a collection of Colony objects
    """
    def __init__(
        self,
        id: int,
        diameter: float,
        edge_cut: float = 0,
        name: str = "",
        center: Union[Tuple[float, float], Tuple[float, float, float]] = None,
        colonies: list = None
    ):
        self.id = id
        self.diameter = diameter

        # Can't set argument default otherwise it is shared across all class instances
        if center is None:
            center = tuple()
        if colonies is None:
            colonies = list()

        # Set property defaults
        self.center = center
        self.items = colonies
        self.edge_cut = edge_cut
        self.name = name

    def __iter__(self):
        return iter([
            self.id,
            self.name,
            self.center,
            self.diameter,
            self.area,
            self.edge_cut,
            self.count
        ])

    @property
    def center(self) -> Union[Tuple[float, float], Tuple[float, float, float]]:
        return self.__center

    @center.setter
    def center(self, val: Union[Tuple[float, float], Tuple[float, float, float]]):
        self.__center = val

    @property
    def edge_cut(self) -> float:
        return self.__edge_cut

    @edge_cut.setter
    def edge_cut(self, val: float):
        self.__edge_cut = val

    def colonies_to_csv(self, save_path: Path, headers: List[str] = None) -> Path:
        """
        Output the data from the colonies collection to a CSV file

        :param save_path: the location to save the CSV data file
        :param headers: a list of strings to use as column headers
        :returns: a Path representing the new file, if successful
        """
        from .file_access import file_safe_name

        if headers is None:
            headers = [
                "Colony ID",
                "Time of appearance",
                "Time of appearance (elapsed minutes)",
                "Center point averaged (row, column)",
                "Colour averaged name",
                "Colour averaged (R,G,B)",
                "Growth rate average",
                "Growth rate",
                "Doubling time average (minutes)",
                "Doubling times (minutes)",
                "First detection (elapsed minutes)",
                "First center point (row, column)",
                "First area (pixels)",
                "First diameter (pixels)",
                "Final detection (elapsed minutes)",
                "Final center point (row, column)",
                "Final area (pixels)",
                "Final diameter (pixels)"
            ]

        return self.__collection_to_csv(
            save_path,
            file_safe_name([f"plate{str(self.id)}", self.name, "colonies"]),
            self.items,
            headers
        )

    def colonies_timepoints_to_csv(self, save_path: Path, headers: List[str] = None) -> Path:
        """
        Output the data from the timepoints in the colonies collection to a CSV file

        :param save_path: the location to save the CSV data file
        :param headers: a list of strings to use as column headers
        :returns: a Path representing the new file, if successful
        """
        from .file_access import file_safe_name

        if headers is None:
            headers = [
                "Colony ID",
                "Date/Time",
                "Elapsed time (minutes)",
                "Area (pixels)",
                "Center (row, column)",
                "Diameter (pixels)",
                "Perimeter (pixels)",
                "Color average (R,G,B)"
            ]

        # Unpack timepoint properties to a flat list
        colony_timepoints = list()
        for colony in self.items:
            for timepoint in colony.timepoints.values():
                colony_timepoints.append([colony.id, *timepoint])

        return self.__collection_to_csv(
            save_path,
            # "_".join(filter(None, [f"plate{str(self.id)}", self.name.replace(" ", "_"), "colony", "timepoints"])),
            file_safe_name([f"plate{str(self.id)}", self.name, "colony", "timepoints"]),
            colony_timepoints,
            headers
        )

    def colonies_rename_sequential(self, start: int = 1) -> int:
        """
        Update the ID numbers of all colonies in the plate colony collection

        :param start: the new initial ID number
        :returns: the final ID number of the renamed sequence
        """
        for i, colony in enumerate(self.items, start = start):
            colony.id = i

        return i

    @staticmethod
    def __collection_to_csv(save_path: Path, file_name: str, data: Collection, headers: List[str] = None) -> Path:
        """
        Output the data from the timepoints in the colonies collection to a CSV file

        :param save_path: the location to save the CSV data file
        :param file_name: the name of the CSV data file
        :param data: a collection of iterables to output as rows to the CSV file
        :param headers: a list of strings to use as column headers
        :returns: a Path representing the new file, if successful
        """
        # Check that a path has been specified and can be found
        if not isinstance(save_path, Path):
            save_path = Path(save_path)
        if not save_path.exists() or str(PurePath(save_path)) == ".":
            raise FileNotFoundError(f"The path '{str(save_path)}' could not be found. Please specify a different save path")

        return save_to_csv(
            data,
            headers,
            save_path.joinpath(file_name)
        )


class PlateCollection(IdentifiedCollection):
    """
    Holds a collection of Plates
    """
    def __init__(self, plates: Collection = None, shape: Tuple[int, int] = None):
        super(PlateCollection, self).__init__(plates)
        if shape is None:
            shape = tuple()

        self.shape = shape

    @property
    def centers(self) -> Union[List[Tuple[float, float]], List[Tuple[float, float, float]]]:
        return [plate.center for plate in self.items]

    @property
    def shape(self) -> Tuple[int, int]:
        return self.__shape

    @shape.setter
    def shape(self, val: Tuple[int, int]):
        if not PlateCollection.__is_valid_shape(val):
            raise ValueError(f"{val} is not a valid shape. All values must be non-negative integers")

        self.__shape = val

    def add(
        self,
        id: int,
        diameter: float,
        edge_cut: float = 0,
        name: str = "",
        center: Union[Tuple[float, float], Tuple[float, float, float]] = None,
        colonies: list = None
    ) -> Plate:
        """
        Create a new Plate and append it to the collection

        :param id: the integer ID number for the plate
        :param diameter: the physical diameter of the plate, in millimeters
        :param colonies: a collection of Colony objects contained in the Plate
        :returns: the new Plate instance
        """

        plate = Plate(
            id = id,
            diameter = diameter,
            edge_cut = edge_cut,
            name = name,
            center = center,
            colonies = colonies
        )

        self.append(plate)

        return plate

    @classmethod
    def from_image(cls, shape: Tuple[int, int], image: ndarray, diameter: float, **kwargs) -> PlateCollection:
        """
        Create a new instance of PlateCollection from an image

        :param shape: row and column boundaries
        :param image: an image containing a set of plates, as a numpy array
        :returns: a new instance of PlateCollection
        """
        plates = cls(shape = shape)
        plates.plates_from_image(image = image, diameter = diameter, **kwargs)

        return plates

    def plates_from_image(
        self,
        image: ndarray,
        diameter: float,
        search_radius: float = 50,
        edge_cut: float = 0,
        labels: Dict[int, str] = dict()
    ) -> List[Plate]:
        """
        Create a collection of Plate instances from an image

        :param image: a grayscale image as a numpy array
        :param diameter: the expected plate diameter, in pixels
        :param search_radius: the distance, in pixels to search around the expected plate diameter
        :param edge_cut: the radius to exclude from imaging analysis, in pixels
        :param labels: a dict of labels for each plate, with the plate ID as a key
        :returns: a list of Plate instances
        """
        from .imaging import get_image_circles

        if not self.shape:
            raise ValueError("The PlateCollection shape property is required, but has not been set")

        plate_coordinates = get_image_circles(
            image,
            int(diameter / 2),
            circle_count = PlateCollection.coordinate_to_index(self.shape),
            search_radius = search_radius
        )

        plates = list()
        for plate_id, coord in enumerate(plate_coordinates, start = 1):
            center, radius = coord
            name = ""
            if plate_id in labels:
                name = labels[plate_id]

            plates.append(self.add(
                id = plate_id,
                diameter = radius * 2,
                edge_cut = edge_cut,
                name = name,
                center = center
            ))

        return plates

    def slice_plate_image(self, image: ndarray, background_color: Tuple = 0) -> Dict[int, ndarray]:
        """
        Split an image into individual plate subimages and delete background

        Slices according to the Plate instances in the current collection

        :param image: an image as a numpy array
        :returns: a doct of plate images with the plate ID number as the key
        """
        from .imaging import cut_image_circle
        images = dict()

        for plate in self.items:
            images[plate.id] = cut_image_circle(
                image,
                center = plate.center,
                radius = plate.radius - plate.edge_cut,
                background_color = background_color
            )

        return images

    @staticmethod
    def coordinate_to_index(coordinate: Tuple[int, int]) -> int:
        """
        Find a positional index for a coordinate

        Starting along columns and then progressing down rows

        :param coordinate: a row, column coordinate tuple
        :returns: a positional index number
        """
        from numpy import prod

        if not PlateCollection.__is_valid_shape(coordinate):
            raise ValueError(
                f"The supplied coordinates, {coordinate}, are not valid. All values must be non-negative integers"
            )

        return prod(coordinate)

    @staticmethod
    def index_to_coordinate(index: int, shape: Tuple[int, int]) -> Tuple[int, int]:
        """
        Calculate row and column numbers for an item index

        Lattice coordinate and item index numbers are 1-based

        :param index: item index number
        :param shape: row and column boundaries
        :returns: row and column coordinate tuple
        """
        if index < 1 or not PlateCollection.__is_valid_shape(shape):
            raise ValueError("The supplied index or shape is not valid. All values must be non-negative integers")

        shape_row, shape_col = shape

        row = ((index - 1) // shape_col) + 1
        col = ((index - 1) % shape_col) + 1

        if row > shape_row or col > shape_col:
            raise IndexError("Index number is greater than the supplied shape size")

        return (row, col)

    @staticmethod
    def __is_valid_shape(shape: Tuple[int, int]) -> bool:
        return (
            all(shape) and
            not any([(not isinstance(val, int) or val < 1) for val in shape])
        )