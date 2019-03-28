# For service integration
import logging
import grpc
import service
import service.service_spec.semantic_segmentation_aerial_pb2_grpc as grpc_bt_grpc
from service.service_spec.semantic_segmentation_aerial_pb2 import Image
import concurrent.futures as futures
import sys
import os
import pathlib
from urllib.error import HTTPError
from service.semantic_segmentation_aerial import SemanticSegmentationAerialModel

logging.basicConfig(
    level=10, format="%(asctime)s - [%(levelname)8s] - %(name)s - %(message)s"
)
log = logging.getLogger("semantic_segmentation_aerial_service")


class SemanticSegmentationAerialServicer(grpc_bt_grpc.SemanticSegmentationAerialServicer):
    """Semantic segmentation for aerial images servicer class to be added to the gRPC stub.
    Derived from protobuf (auto-generated) class."""

    def __init__(self):
        log.debug("SemanticSegmentationAerialServicer created!")

        self.result = Image()

        self.input_dir = "./service/temp/input"
        self.output_dir = "./service/temp/output"
        service.serviceUtils.initialize_diretories([self.input_dir, self.output_dir])

        self.root_path = pathlib.Path.cwd()
        self.model_path = self.root_path / "service/models/segnet_final_reference.pth"
        if not self.model_path.is_file():
            log.error("Model ({}) not found. Please run download_models.sh.".format(self.model_path))
            return
        self.model = SemanticSegmentationAerialModel(self.model_path)

    def treat_inputs(self, request, arguments, created_images):
        """Treats gRPC inputs and assembles lua command. Specifically, checks if required field have been specified,
        if the values and types are correct and, for each input/input_type adds the argument to the lua command."""

        file_index_str = ""
        image_path = ""
        window_size = 0
        stride = 0

        for field, values in arguments.items():
            # var_type = values[0]
            # required = values[1] Not being used now but required for future automation steps
            default = values[2]

            # Tries to retrieve argument from gRPC request
            try:
                arg_value = eval("request.{}".format(field))
            except Exception as e:  # AttributeError if trying to access a field that hasn't been specified.
                log.error(e)
                return False

            if field == "input":
                log.debug("Received input image data.")
            else:
                log.debug("Received request.{} = {}".format(field, arg_value))

            # Deals with each field (or field type) separately.
            if field == "input":
                assert (request.input != ""), "Input image field should not be empty."
                try:
                    image_path, file_index_str = \
                        service.treat_image_input(arg_value, self.input_dir, "{}".format(field))
                    log.debug("Field: {}. Image path: {}".format(field, image_path))
                    created_images.append(image_path)
                except Exception as e:
                    log.error(e)
                    raise
            elif field == "window_size":
                    # If empty, fill with default, else check if valid
                    if request.window_size == 0 or request.window_size == "":
                        window_size = default
                    else:
                        try:
                            window_size = int(request.window_size)
                        except Exception as e:
                            log.error(e)
                            raise
            elif field == "stride":
                # If empty, fill with default, else check if valid
                if request.stride == 0 or request.stride == "":
                    stride = default
                else:
                    try:
                        stride = int(request.stride)
                    except Exception as e:
                        log.error(e)
                        raise
                if stride > request.window_size:
                    log.error('Stride must be smaller than window size')
            else:
                log.error("Error. Required request field not found.")
                return False

        return image_path, window_size, stride, file_index_str

    def segment_aerial_image(self, request, context):
        """Increases the resolution of a given image (request.image) """

        # Store the names of the images to delete them afterwards
        created_images = []

        # Python command call arguments. Key = argument name, value = tuple(type, required?, default_value)
        arguments = {"input": ("image", True, None),
                     "window_size": ("int", True, 256),
                     "stride": ("int", False, 32)}

        # Treat inputs
        try:
            image_path, window_size, stride, file_index_str = self.treat_inputs(request, arguments, created_images)
        except HTTPError as e:
            error_message = "Error downloading the input image \n" + e.read()
            log.error(error_message)
            self.result.data = error_message
            return self.result
        except Exception as e:
            log.error(e)
            self.result.data = e
            return self.result

        # Get output file path
        input_filename = os.path.split(created_images[0])[1]
        log.debug("Input file name: {}".format(input_filename))
        output_image_path = self.output_dir + '/' + input_filename
        log.debug("Output image path: {}".format(output_image_path))
        created_images.append(output_image_path)

        # Actual call to the model
        self.model.segment(image_path, window_size, stride, output_image_path)

        # Prepare gRPC output message
        self.result = Image()
        if input_filename.split('.')[1] == 'png':
            log.debug("Encoding from PNG.")
            self.result.data = service.png_to_base64(output_image_path).decode("utf-8")
        else:
            log.debug("Encoding from JPG.")
            self.result.data = service.jpg_to_base64(output_image_path, open_file=True).decode("utf-8")
        log.debug("Output image generated. Service successfully completed.")

        for image in created_images:
            service.serviceUtils.clear_file(image)

        return self.result


def serve(max_workers=5, port=7777):
    """The gRPC serve function.

    Params:
    max_workers: pool of threads to execute calls asynchronously
    port: gRPC server port

    Add all your classes to the server here.
    (from generated .py files by protobuf compiler)"""

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    grpc_bt_grpc.add_SemanticSegmentationAerialServicer_to_server(
        SemanticSegmentationAerialServicer(), server)
    server.add_insecure_port('[::]:{}'.format(port))
    log.debug("Returning server!")
    return server


if __name__ == '__main__':
    """Runs the gRPC server to communicate with the Snet Daemon."""
    parser = service.common_parser(__file__)
    args = parser.parse_args(sys.argv[1:])
    service.serviceUtils.main_loop(serve, args)
