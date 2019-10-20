﻿# System modules
import sys
import glob
import math
import statistics
import argparse
import pickle
from pathlib import Path
from datetime import datetime, timedelta
from operator import attrgetter
from distutils.util import strtobool

# Third party modules
import numpy as np
from skimage.io import imread, imsave
import matplotlib.pyplot as plt

# Local modules
from colonyscanalyser import (
    utilities,
    file_access,
    imaging,
    plotting,
    plots,
    colony
)
from .colony import timepoints_from_image


def get_plate_directory(parent_path, row, col, create_dir = True):
    """
    Determine the directory path for a specified plate

    Can create the directory if needed

    :param parent_path: a path object
    :param row: a lattice co-ordinate row
    :param col: a lattice co-ordinate column
    :param create_dir: specify if the directory should be created
    :returns: a path object for the specified plate
    """
    from pathlib import Path

    child_path = '_'.join(['row', str(row), 'col', str(col)])
    if create_dir:
        return file_access.create_subdirectory(parent_path, child_path)
    else:
        return parent_path.joinpath(child_path)


def get_image_timestamps(image_paths, elapsed_minutes = False):
    """
    Get timestamps from a list of images

    Assumes images have a file name with as timestamp
    Timestamps should be in YYYYMMDD_HHMM format

    :param images: a list of image file path objects
    :param elapsed_minutes: return timestamps as elapsed integer minutes
    :returns: a list of timestamps
    """
    time_points = list()

    # Get date and time information from filenames
    dates = [str(image.name[:-8].split("_")[-2]) for image in image_paths]
    times = [str(image.name[:-4].split("_")[-1]) for image in image_paths]
    
    # Convert string timestamps to Python datetime objects
    for i, date in enumerate(dates):
        time_points.append(datetime.combine(datetime.strptime(date, "%Y%m%d"),datetime.strptime(times[i], "%H%M").time()))
    
    if elapsed_minutes:
        # Store time points as elapsed minutes since start
        time_points_elapsed = list()
        for time_point in time_points:
            time_points_elapsed.append(int((time_point - time_points[0]).total_seconds() / 60))
        time_points = time_points_elapsed

    return time_points


def get_plate_images(image, plate_coordinates, edge_cut = 100):
    """
    Split image into lattice subimages and delete background
    
    :param img: a black and white image as a numpy array
    :param plate_coordinates: a list of centers and radii
    :param edge_cut: a radius, in pixels, to remove from the outer edge of the plate
    :returns: a list of plate images
    """
    plates = []
    
    for coordinate in plate_coordinates:
        center, radius = coordinate
        plates.append(imaging.cut_image_circle(image, center, radius - edge_cut))
    
    return plates


def segment_image(plate, plate_mask, plate_noise_mask, area_min = 5):
    """
    Finds all colonies on a plate and returns an array of co-ordinates

    If a co-ordinate is occupied by a colony, it contains that colonies labelled number

    :param plate: a black and white image as a numpy array
    :param mask: a black and white image as a numpy array
    :param plate_noise_mask: a black and white image as a numpy array
    :returns: a segmented and labelled image as a numpy array
    """
    from scipy import ndimage
    from skimage.morphology import remove_small_objects
    from skimage.measure import regionprops, label

    plate = imaging.remove_background_mask(plate, plate_mask)
    plate_noise_mask = imaging.remove_background_mask(plate_noise_mask, plate_mask)

    # Subtract an image of the first (i.e. empty) plate to remove static noise
    plate[plate_noise_mask] = 0

    # Fill any small gaps
    plate = ndimage.morphology.binary_fill_holes(plate)

    # Remove background noise
    plate = remove_small_objects(plate, min_size = area_min)

    #versions <0.16 do not allow for a mask
    #colonies = clear_border(pl_th, buffer_size = 1, mask = pl_th)

    colonies = label(plate)

    # Exclude objects that are too eccentric
    rps = regionprops(colonies, coordinates = "rc")
    for rp in rps:
        # Eccentricity of zero is a perfect circle
        # Circularity of 1 is a perfect circle
        circularity = (4 * math.pi * rp.area) / (rp.perimeter * rp.perimeter)

        if rp.eccentricity > 0.6 or circularity < 0.80:
            colonies[colonies == rp.label] = 0

    # Result is a 2D co-ordinate array
    # Each co-ordinate contains either zero or a unique colony number
    # The colonies are numbered from one to the total number of colonies on the plate
    return colonies


def segment_plate_timepoints(plate_images_list, date_times):
    """
    Build an array of segmented image data for all available time points

    Takes list of pre-processed plate images of size (total timepoints)

    :param plate_images_list: a list of black and white images as numpy arrays
    :param date_times: an ordered list of datetime objects
    :returns: a segmented and labelled list of images as numpy arrays
    :raises ValueError: if the size of plate_images_list and date_times do not match
    """
    # Check that the number of datetimes corresponds with the number of image timepoints
    if len(date_times) != len(plate_images_list):
        raise ValueError("Unable to process image timepoints. The supplied list of dates/times does not match the number of image timepoints")

    segmented_images = []
    plate_noise_mask = []
    # Loop through time points for the plate
    for i, plate_image in enumerate(plate_images_list, start=1):
        plate_mask = plate_image > 0
        # Create a noise mask from the first plate
        if i == 1:
            plate_noise_mask = plate_image
        # Build a 2D array of colony co-ordinate data for the plate image
        segmented_image = segment_image(plate_image, plate_mask, plate_noise_mask, area_min = 8)
        # segmented_images is an array of size (total plates)*(total timepoints)
        # Each time point element of the array contains a co-ordinate array of size (total image columns)*(total image rows)
        segmented_images.append(segmented_image)

    return segmented_images

def main():
    parser = argparse.ArgumentParser(
        description = "An image analysis tool for measuring microorganism colony growth",
        formatter_class = argparse.ArgumentDefaultsHelpFormatter
        )
    parser.add_argument("path", type = str,
                       help = "Image files location", default = None)
    parser.add_argument("-v", "--verbose", type = int, default = 1,
                       help = "Information output level")
    parser.add_argument("-dpi", "--dots_per_inch", type = int, default = 2540,
                       help = "The image DPI (dots per inch) setting")
    parser.add_argument("--plate_size", type = int, default = 100,
                       help = "The plate diameter, in millimetres")
    parser.add_argument("--plate_lattice", type = int, nargs = 2, default = (3, 2),
                        metavar = ("ROW", "COL"),
                        help = "The row and column co-ordinate layout of plates. Example usage: --plate_lattice 3 3")
    parser.add_argument("-pos", "--plate_position", type = int, nargs = 2, default = argparse.SUPPRESS,
                        metavar = ("ROW", "COL"),
                        help = "The row and column co-ordinates of a single plate to study in the plate lattice. Example usage: --plate_position 2 1 (default: all)")
    parser.add_argument("--save_plots", type = int, default = 1,
                        help = "The detail level of plot images to store on disk")
    parser.add_argument("--use_saved", type = strtobool, default = True,
                        help = "Allow or prevent use of previously calculated data")

    args = parser.parse_args()
    BASE_PATH = args.path
    VERBOSE = args.verbose
    PLATE_SIZE = imaging.mm_to_pixels(args.plate_size - 5, dots_per_inch = args.dots_per_inch)
    PLATE_LATTICE = tuple(args.plate_lattice)
    if "plate_position" not in args:
        PLATE_POSITION = None
    else:
        PLATE_POSITION = args.plate_position
    SAVE_PLOTS = args.save_plots
    USE_SAVED = args.use_saved

    if PLATE_POSITION is not None:
        PLATE_POSITION = tuple(PLATE_POSITION)
        if utilities.coordinate_to_index_number(PLATE_POSITION) > utilities.coordinate_to_index_number(PLATE_LATTICE):
            raise ValueError(f"The supplied plate position coordinate ({PLATE_POSITION})is outside the plate grid ({PLATE_LATTICE})")

    if VERBOSE >= 1:
        print("Starting ColonyScanalyser analysis")

    # Resolve working directory
    if BASE_PATH is None:
        raise ValueError("A path to a working directory must be supplied")
    else:
        BASE_PATH = Path(args.path).resolve()
    if not BASE_PATH.exists():
        raise EnvironmentError(f"The supplied folder path could not be found: {BASE_PATH}")
    if VERBOSE >= 1:
        print(f"Working directory: {BASE_PATH}")

    # Find images in working directory
    image_formats = ["tif", "tiff", "png"]
    image_files = file_access.get_files_by_type(BASE_PATH, image_formats)
    
    #Check if images have been loaded
    if len(image_files) > 0:
        if VERBOSE >= 1:
            print(f"{len(image_files)} images found")
    else:
        raise IOError(f"No images could be found in the supplied folder path. Images are expected in these formats: {image_formats}")
    
    # Get date and time information from filenames
    time_points = get_image_timestamps(image_files)
    time_points_elapsed = get_image_timestamps(image_files, elapsed_minutes = True)
    if len(time_points) != len(image_files) or len(time_points) != len(image_files):
        raise IOError("Unable to load timestamps from all image filenames. Please check that images have a filename with YYYYMMDD_HHMM timestamps")

    # Check if processed image data is already stored and can be loaded
    segmented_image_data_filename = "processed_data"
    if USE_SAVED:
        if VERBOSE >= 1:
            print("Attempting to load cached data")
        plate_colonies = file_access.load_file(
            BASE_PATH.joinpath("data", segmented_image_data_filename),
            file_access.CompressionMethod.LZMA,
            pickle = True
            )
        # Check that segmented image data has been loaded for all plates
        if VERBOSE >= 1 and plate_colonies is not None and len(plate_colonies) == utilities.coordinate_to_index_number(PLATE_LATTICE):
            print("Successfully loaded cached data")
        else:
            print("Unable to load cached data, starting image processing")
            
    # Process images
    plates_list = dict()
    plates_list_segmented = dict()
    if not USE_SAVED or plate_colonies is None:
        plate_coordinates = None
        # Loop through and preprocess image files
        for ifn, image_file in enumerate(image_files):

            if VERBOSE >= 1:
                print(f"Processing image number {ifn + 1} of {len(image_files)}")

            if VERBOSE >= 2:
                print(f"Imaging date-time: {time_points[ifn].strftime('%Y%m%d %H%M')}")

            if VERBOSE >= 2:
                print(f"Processing image: {image_file}")
            img = imread(str(image_file), as_gray = True)

            if VERBOSE >= 2:
                print(f"Locate plates in image: {image_file}")
            # Only find centers using first image. Assume plates do not move
            if plate_coordinates is None:
                plate_coordinates = imaging.get_image_circles(
                    img,
                    int(PLATE_SIZE / 2),
                    circle_count = utilities.coordinate_to_index_number(PLATE_LATTICE),
                    search_radius = 50
                    )

            if VERBOSE >= 2:
                print("Split image into plates")
            plates = get_plate_images(img, plate_coordinates, edge_cut = 60)
            
            if PLATE_POSITION is not None:
                # Save image for only a single plate
                plate_index = utilities.coordinate_to_index_number(PLATE_POSITION)
                if plate_index not in plates_list:
                    plates_list[plate_index] = list()
                plates_list[plate_index].append(plates[plate_index - 1])
            else:
                # Save images for all plates
                for i, plate in enumerate(plates, start = 1):
                    # Store the image data from the current plate timepoint
                    if i not in plates_list:
                        plates_list[i] = list()
                    plates_list[i].append(plate)
                        
        # Loop through plates and segment images at all timepoints
        for plate_id, plate_timepoints in sorted(plates_list.items()):
            row, col = utilities.index_number_to_coordinate(plate_id, PLATE_LATTICE)
            if VERBOSE >= 1:
                print(f"Segmenting images from plate #{plate_id}, in position row {row} column {col}")

            # plates_list is an array of size (total plates)*(total timepoints)
            # Each time point element of the array contains a co-ordinate array of size (total image columns)*(total image rows)
            segmented_plate_timepoints = segment_plate_timepoints(plate_timepoints, time_points)
            if segmented_plate_timepoints is None:
                raise RuntimeError("Unable to segment image data for plate")
            
            # Ensure labels remain constant
            segmented_plate_timepoints = imaging.standardise_labels_timeline(segmented_plate_timepoints)

            # Store the images for this plate
            plates_list_segmented[plate_id] = segmented_plate_timepoints

            # Save segmented image plot for each timepoint
            if SAVE_PLOTS >= 2:
                if VERBOSE >= 1:
                    print("Saving segmented image plots for each plate. This process will take a long time")
                for j, segmented_plate_timepoint in enumerate(segmented_plate_timepoints):
                    if VERBOSE >= 3:
                        print(f"Saving segmented image plot for time point {j + 1} of {len(segmented_plate_timepoints)}")
                    plots_path = file_access.create_subdirectory(BASE_PATH, "plots")
                    save_path = get_plate_directory(plots_path, row, col, create_dir = True)
                    save_path = file_access.create_subdirectory(save_path, "segmented_images")
                    image_path = plots.plot_plate_segmented(plate_timepoints[j], segmented_plate_timepoint, (row, col), time_points[j], save_path)
                    if image_path is not None:
                        if VERBOSE >= 3:
                            print(f"Saved segmented image plot to: {str(image_path)}")
                    else:
                        print(f"Error: Unable to save segmented image plot for plate at row {row} column {col}")

        # Loop through plates and colony objects for each colony found
        if VERBOSE >= 1:
            print("Tracking individual colonies")
        from collections import defaultdict
        plate_colonies = defaultdict(dict)
        for plate_id, plate_images in sorted(plates_list_segmented.items()):
            if VERBOSE >= 1:
                print(f"Tacking colonies on plate {plate_id} of {len(plates_list_segmented)}")

            # Process image at each time point
            for j, plate_image in enumerate(plate_images):
                if VERBOSE >= 3:
                    print(f"Tacking colonies at time point {j + 1} of {len(plate_images)}")

                # Store data for each colony at every timepoint it is found
                plate_colonies[plate_id] = timepoints_from_image(plate_colonies[plate_id], plate_image, time_points[j], time_points_elapsed[j])

            # Remove objects that do not have sufficient data points, usually just noise
            plate_colonies[plate_id] = dict(filter(lambda elem: len(elem[1].timepoints) > len(time_points) * 0.2, plate_colonies[plate_id].items()))
            # Remove object that do not show growth, these are not colonies
            plate_colonies[plate_id] = dict(filter(lambda elem: elem[1].growth_rate > 1, plate_colonies[plate_id].items()))
            # Colonies that appear with a large area are most likely already merged colonies, not new colonies
            plate_colonies[plate_id] = dict(filter(lambda elem: elem[1].timepoint_first.area < 50, plate_colonies[plate_id].items()))

            if VERBOSE >= 1:
                print(f"Colony data stored for {len(plate_colonies[plate_id].keys())} colonies on plate {plate_id}")

    # Store pickled data to allow quick re-use
    save_path = file_access.create_subdirectory(BASE_PATH, "data")
    save_path = save_path.joinpath(segmented_image_data_filename)
    save_status = file_access.save_file(save_path, plate_colonies, file_access.CompressionMethod.LZMA)
    if VERBOSE >= 1:
        if save_status:
            print(f"Cached data saved to {save_path}")
        else:
            print(f"An error occurred and cached data could not be written to disk at {save_path}")

    # Store colony data in CSV format
    if VERBOSE >= 1:
        print("Saving data to CSV")
    save_path = BASE_PATH.joinpath("data")
    for plate_id, plate in sorted(plate_colonies.items()):
        headers = [
            "Colony ID",
            "Time of appearance",
            "Time of appearance (elapsed minutes)",
            "Center point averaged (row, column)",
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

        # Save data for all colonies on one plate
        file_access.save_to_csv(
            plate.values(),
            headers,
            save_path.joinpath(f"plate{plate_id}_colonies")
            )

        # Save data for each colony on a plate
        headers = [
            "Colony ID",
            "Date/Time",
            "Elapsed time (minutes)",
            "Area (pixels)",
            "Center (row, column)",
            "Diameter (pixels)",
            "Perimeter (pixels)"
        ]
        colony_timepoints = list()
        for colony_id, colony in plate.items():
            for timepoint in colony.timepoints.values():
                # Unpack timepoint properties to a flat list
                colony_timepoints.append([colony_id, *timepoint])
                
        file_access.save_to_csv(
            colony_timepoints,
            headers,
            save_path.joinpath(f"plate{plate_id}_colony_timepoints")
            )
    
    if VERBOSE >= 1:
        print("Saving plots")
    # Plot colony growth curves and time of appearance for the plate
    if SAVE_PLOTS >= 2:
        for plate_id, plate in plate_colonies.items():
            row, col = utilities.index_number_to_coordinate(plate_id, PLATE_LATTICE)
            save_path = get_plate_directory(BASE_PATH.joinpath("plots"), row, col, create_dir = True)
            plate_item = {plate_id : plate}
            plots.plot_growth_curve(plate_item, time_points_elapsed, save_path)
            plots.plot_appearance_frequency(plate_item, time_points_elapsed, save_path)
            plots.plot_appearance_frequency(plate_item, time_points_elapsed, save_path, bar = True)

    # Plot colony growth curves for all plates
    if SAVE_PLOTS >= 1:
        save_path = file_access.create_subdirectory(BASE_PATH, "plots")
        plots.plot_growth_curve(plate_colonies, time_points_elapsed, save_path)
        plots.plot_appearance_frequency(plate_colonies, time_points_elapsed, save_path)
        plots.plot_appearance_frequency(plate_colonies, time_points_elapsed, save_path, bar = True)
        plots.plot_doubling_map(plate_colonies, time_points_elapsed, save_path)

    if VERBOSE >= 1:
        print(f"ColonyScanalyser analysis completed for: {BASE_PATH}")

    sys.exit()


if __name__ == "__main__":

    main()