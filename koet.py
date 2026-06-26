#!/usr/bin/python3
import json
import os
import sys
import socket
import datetime
import subprocess
import shlex
import time
from shutil import copyfile
from decimal import Decimal
import argparse
from math import ceil
import re
import csv
import statistics
from pathlib import Path

try:
    import distro
except ImportError:
    sys.exit('\033[91m' + "QUIT: " + '\033[0m' +
             "Cannot import distro. Check python3-distro is installed\n")

# Colorful constants
RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
NOCOLOR = '\033[0m'

# KPI + runtime acceptance values
MAX_AVG_LATENCY = 1.00  # Acceptance value should be 1 msec or less
FPING_COUNT = 500  # Acceptance value should be 500 or more
PERF_RUNTIME = 1200  # Acceptance value should be 1200 or more
MIN_NSD_THROUGHPUT = 2000  # Acceptance value with lots of margin

# GITHUB URL
GIT_URL = "https://github.com/cdmaestas/SpectrumScale_NETWORK_READINESS"

# IP RE
IPPATT = re.compile(r'.*inet\s+(?P<ip>.*)\/\d+')

# This script version, independent from the JSON versions
KOET_VERSION = "1.17"


def fatal(msg):
    sys.exit(RED + "QUIT: " + NOCOLOR + msg)


def load_json(json_file_str):
    try:
        with open(json_file_str, "r") as json_file:
            return json.load(json_file)
    except Exception:
        fatal("Cannot open JSON file: " + json_file_str)


def json_file_loads(json_file_str):
    try:
        with open(json_file_str, "r") as f:
            json.load(f)
        return True
    except Exception:
        return False


def write_json_file_from_dictionary(hosts_dictionary, json_file_str):
    try:
        with open(json_file_str, "w") as json_file:
            json.dump(hosts_dictionary, json_file)
            print(GREEN + "OK: " + NOCOLOR + "JSON file: " + json_file_str +
                  " [over]written")
    except Exception:
        fatal("Cannot write JSON file: " + json_file_str)


def check_localnode_is_in(hosts_dictionary):
    try:
        result = subprocess.run(['ip', 'addr', 'show'],
                                capture_output=True, text=True)
        raw_out = result.stdout
    except Exception:
        fatal("cannot list ip address on local node\n")
    iplist = IPPATT.findall(raw_out)
    for node in hosts_dictionary.keys():
        if node in iplist:
            return
    fatal("Local node is not part of the test\n")


def estimate_runtime(hosts_dictionary, fp_count, perf_runtime):
    number_of_hosts = len(hosts_dictionary)
    estimated_rt_fp = number_of_hosts * fp_count
    estimated_rt_perf = (number_of_hosts + 1) * (20 + perf_runtime)
    estimated_runtime = estimated_rt_fp + estimated_rt_perf
    return max(int(ceil(estimated_runtime / 60.)), 2)


def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-l', '--latency',
        action='store',
        dest='max_avg_latency',
        help='The KPI latency value as float. '
             'The maximum required value for certification is '
             + str(MAX_AVG_LATENCY) + ' msec',
        metavar='KPI_LATENCY',
        type=float,
        default=1.0)
    parser.add_argument(
        '-c', '--fping_count',
        action='store',
        dest='fping_count',
        help='The number of fping counts to run per node and test. '
             'The value has to be at least 2 seconds.'
             'The minimum required value for certification is '
             + str(FPING_COUNT),
        metavar='FPING_COUNT',
        type=int,
        default=500)
    parser.add_argument(
        '--hosts',
        action='store',
        dest='hosts',
        help='IP addresses of hosts on CSV format. '
             'Using this overrides the hosts.json file.',
        metavar='HOSTS_CSV',
        type=str,
        default="")
    parser.add_argument(
        '-m', '--min_throughput',
        action='store',
        dest='perf_throughput',
        help='The minimum MB/sec required to pass the test. '
             'The minimum required value for certification is '
             + str(MIN_NSD_THROUGHPUT),
        metavar='KPI_THROUGHPUT',
        type=int,
        default=2000)
    parser.add_argument(
        '-p', '--perf_runtime',
        action='store',
        dest='perf_runtime',
        help='The seconds of nsdperf runtime per test. '
             'The value has to be at least 10 seconds. '
             'The minimum required value for certification is '
             + str(PERF_RUNTIME),
        metavar='PERF_RUNTIME',
        type=int,
        default=1200)
    parser.add_argument(
        '--rdma',
        action='store',
        dest='rdma',
        help='Enables RDMA and ports to be check on CSV format '
             '(ib0,ib1,...). Must be using OS device names, not mlx names.',
        metavar='PORTS_CSV',
        default="")
    parser.add_argument(
        '--rpm_check_disabled',
        action='store_true',
        dest='no_rpm_check',
        help='Disables the RPM prerequisites check. Use only if you are '
             'sure all required software is installed and no RPM were used '
             'to install the required prerequisites',
        default=False)
    parser.add_argument(
        '--save-hosts',
        action='store_true',
        dest='save_hosts',
        help='[over]writes hosts.json with the hosts passed with '
             '--hosts. It does not prompt for confirmation when overwriting',
        default=False)
    parser.add_argument('-v', '--version', action='version',
                        version='KOET ' + KOET_VERSION)

    args = parser.parse_args()
    if args.max_avg_latency <= 0:
        fatal("KPI latency cannot be zero or negative number\n")
    if args.fping_count <= 1:
        fatal("fping count cannot be less than 2\n")
    if args.perf_throughput <= 0:
        fatal("KPI throughput cannot be zero or negative number\n")
    if args.perf_runtime <= 9:
        fatal("nsdperf runtime cannot be less than 10 seconds\n")
    if 'mlx' in args.rdma:
        fatal("RDMA ports must be OS names (ib0,ib1,...)\n")

    cli_hosts = False
    hosts_dictionary = {}
    if args.hosts != "":
        cli_hosts = True
        try:
            hosts_dictionary = {h: "ECE" for h in args.hosts.split(",")}
        except Exception:
            fatal("hosts parameter is not on CSV format")

    rdma_ports_list = []
    if args.rdma != "":
        rdma_test = True
        try:
            rdma_ports_list = args.rdma.split(",")
        except Exception:
            fatal("rdma parameter is not on CSV format")
    else:
        rdma_test = False

    if args.save_hosts and not cli_hosts:
        fatal("cannot generate hosts file if hosts not passed with --hosts")

    return (round(args.max_avg_latency, 2), args.fping_count,
            args.perf_runtime, args.perf_throughput,
            cli_hosts, hosts_dictionary, rdma_test, rdma_ports_list,
            args.no_rpm_check, args.save_hosts)


def check_kpi_is_ok(max_avg_latency, fping_count, perf_bw, perf_rt):
    return (
        max_avg_latency <= MAX_AVG_LATENCY,
        fping_count >= FPING_COUNT,
        perf_bw >= MIN_NSD_THROUGHPUT,
        perf_rt >= PERF_RUNTIME,
    )


def show_header(koet_h_version, json_version,
                estimated_runtime_str, max_avg_latency,
                fping_count, perf_throughput, perf_runtime):
    while True:
        print("")
        print(GREEN + "Welcome to KOET, version " + koet_h_version + NOCOLOR)
        print("")
        print("JSON files versions:")
        print("\tsupported OS:\t\t" + json_version['supported_OS'])
        print("\tpackages: \t\t" + json_version['packages'])
        print("\tpackages RDMA:\t\t" + json_version['packages_rdma'])
        print("")
        print("Please use " + GIT_URL +
              " to get latest versions and report issues about this tool.")
        print("")
        print("The purpose of KOET is to obtain network metrics "
              "for a number of nodes.")
        print("")
        lat_kpi_ok, fping_kpi_ok, perf_kpi_ok, perf_rt_ok = check_kpi_is_ok(
            max_avg_latency, fping_count, perf_throughput, perf_runtime)
        if lat_kpi_ok:
            print(GREEN + "The latency KPI value of " + str(max_avg_latency) +
                  " msec is good to certify the environment" + NOCOLOR)
        else:
            print(YELLOW + "WARNING: " + NOCOLOR +
                  "The latency KPI value of " + str(max_avg_latency) +
                  " msec is too high to certify the environment")
        print("")
        if fping_kpi_ok:
            print(GREEN + "The fping count value of " + str(fping_count) +
                  " ping per test and node is good to certify the "
                  "environment" + NOCOLOR)
        else:
            print(YELLOW + "WARNING: " + NOCOLOR +
                  "The fping count value of " + str(fping_count) +
                  " ping per test and node is not enough "
                  "to certify the environment")
        print("")
        if perf_kpi_ok:
            print(GREEN + "The throughput value of " + str(perf_throughput) +
                  " MB/sec is good to certify the environment" + NOCOLOR)
        else:
            print(YELLOW + "WARNING: " + NOCOLOR +
                  "The throughput value of " + str(perf_throughput) +
                  " MB/sec is not enough to certify the environment")
        print("")
        if perf_rt_ok:
            print(GREEN + "The performance runtime value of " +
                  str(perf_runtime) +
                  " second per test and node is good to certify the "
                  "environment" + NOCOLOR)
        else:
            print(YELLOW + "WARNING: " + NOCOLOR +
                  "The performance runtime value of " + str(perf_runtime) +
                  " second per test and node is not enough "
                  "to certify the environment")
        print("")
        print(YELLOW +
              "It requires remote ssh passwordless between all nodes for user "
              "root already configured" + NOCOLOR)
        print("")
        print(YELLOW + "This test run estimation is " +
              estimated_runtime_str + " minutes" + NOCOLOR)
        print("")
        print(RED +
              "This software comes with absolutely no warranty of any kind. "
              "Use it at your own risk" + NOCOLOR)
        print("")
        print(RED +
              "NOTE: The bandwidth numbers shown in this tool are for a very "
              "specific test. This is not a storage benchmark." + NOCOLOR)
        print(RED +
              "They do not necessarily reflect the numbers you would see with "
              "Storage Scale and your particular workload" + NOCOLOR)
        print("")
        run_this = input("Do you want to continue? (y/n): ")
        if run_this.lower() == 'y':
            break
        if run_this.lower() == 'n':
            sys.exit("Have a nice day! Bye.\n")
    print("")


def check_os_redhat(os_dictionary):
    dist_str = distro.name() + " " + distro.version()
    # Prefix used to find any entry for this major version family
    # e.g. "Red Hat Enterprise Linux 9" matches 9.0, 9.1, 9.2, ...
    major_family = distro.name() + " " + distro.major_version()

    if dist_str in os_dictionary:
        # Exact match: honour whatever the JSON says (OK or NOK)
        if os_dictionary[dist_str] != 'OK':
            fatal(dist_str + " is not a supported OS for this tool\n")
    else:
        # Unknown point release: supported if any entry in this major version
        # family is marked OK (forward-compatible within a major version)
        family_ok = any(
            v == 'OK' for k, v in os_dictionary.items()
            if k.startswith(major_family)
        )
        if not family_ok:
            fatal(dist_str + " is not a supported OS for this tool\n")

    return int(distro.major_version()) >= 8


def get_json_versions(os_dictionary, packages_dictionary, packages_rdma_dict):
    json_version = {}
    try:
        json_version['supported_OS'] = os_dictionary['json_version']
    except Exception:
        fatal("Cannot load version from supported OS JSON")
    try:
        json_version['packages'] = packages_dictionary['json_version']
    except Exception:
        fatal("Cannot load version from packages JSON")
    try:
        json_version['packages_rdma'] = packages_rdma_dict['json_version']
    except Exception:
        fatal("Cannot load version from packages RDMA JSON")
    return json_version


def check_distribution():
    what_dist = distro.distro_release_info()['id']
    if what_dist in ("redhat", "centos", "rocky"):
        return what_dist
    fatal("this only runs on Red Hat, CentOS, or Rocky Linux\n")


def ssh_rpm_is_installed(host, rpm_package):
    try:
        return subprocess.call(
            ['ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'LogLevel=error',
             host, 'rpm', '-q', rpm_package],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        fatal("cannot run rpm over ssh on host " + host)


def ssh_service_is_up(host, service_name):
    try:
        return_code = subprocess.call(
            ['ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'LogLevel=error',
             host, 'systemctl', 'is-active', '--quiet', service_name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        fatal("cannot run systemctl over ssh on host " + host)
    return return_code == 0


def firewalld_check(hosts_dictionary):
    errors = 0
    for host in hosts_dictionary.keys():
        if ssh_service_is_up(host, "firewalld"):
            print(RED + "ERROR: " + NOCOLOR +
                  "on host " + host + " the firewalld service is running")
            errors += 1
        else:
            print(GREEN + "OK: " + NOCOLOR +
                  "on host " + host + " the firewalld service is not running")
    if errors > 0:
        fatal("Fix the firewalld status before running this tool again.\n")


def check_tcp_port_free(hosts_dictionary, tcpport):
    errors = 0
    for host in hosts_dictionary.keys():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        if sock.connect_ex((host, tcpport)) == 0:
            errors += 1
            print(RED + "ERROR: " + NOCOLOR +
                  "on host " + str(host) + " TCP port " + str(tcpport) +
                  " seems to be not free")
        else:
            print(GREEN + "OK: " + NOCOLOR +
                  "on host " + str(host) + " TCP port " + str(tcpport) +
                  " seems to be free")
    if errors > 0:
        fatal("TCP port " + str(tcpport) + " is not free in all hosts")


def check_permission_files():
    readable_files = ["hosts.json", "makefile", "nsdperf.C", "packages.json",
                      "packages_rdma.json", "packages_rdma_rh8.json",
                      "supported_OS.json"]
    executable_files = ["nsdperfTool.py"]

    read_error = False
    for f in readable_files:
        if not os.access(f, os.R_OK):
            read_error = True
            print(RED + "ERROR: " + NOCOLOR +
                  "cannot read file " + str(f) +
                  ". Have the POSIX ACL been changed?")
    exec_error = False
    for f in executable_files:
        if not os.access(f, os.X_OK):
            exec_error = True
            print(RED + "ERROR: " + NOCOLOR +
                  "cannot execute file " + str(f) +
                  ". Have the POSIX ACL been changed?")
    return read_error or exec_error


def host_packages_check(hosts_dictionary, packages_dictionary):
    errors = 0
    for host in hosts_dictionary.keys():
        for rpm_package in packages_dictionary.keys():
            if rpm_package != "json_version":
                current_package_rc = ssh_rpm_is_installed(host, rpm_package)
                expected_package_rc = packages_dictionary[rpm_package]
                if current_package_rc == expected_package_rc:
                    print(GREEN + "OK: " + NOCOLOR +
                          "on host " + host + " the " + rpm_package +
                          " installation status is as expected")
                else:
                    print(RED + "ERROR: " + NOCOLOR +
                          "on host " + host + " the " + rpm_package +
                          " installation status is *NOT* as expected")
                    errors += 1
    if errors > 0:
        fatal("Fix the packages before running this tool again.\n")


def ssh_file_exists(host, fileurl):
    try:
        return subprocess.call(
            ['ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'LogLevel=error',
             host, 'which', fileurl],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        fatal("cannot run ls over ssh on host " + host)


def ssh_rdma_ports_are_up(host, rdma_ports_list):
    errors = 0
    for port in rdma_ports_list:
        return_code = subprocess.call(
            ['ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'LogLevel=error',
             host, 'ibdev2netdev', '|', 'grep', port, '|', 'grep', '"(Up)"'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if return_code == 0:
            print(GREEN + "OK: " + NOCOLOR +
                  "on host " + host + " the RDMA port " + port +
                  " is on UP state")
        else:
            print(RED + "ERROR: " + NOCOLOR +
                  "on host " + host + " the RDMA port " + port +
                  " is *NOT* on UP state")
            errors += 1
    return errors == 0


def check_rdma_port_mode(hosts_ports_dict):
    errors = 0
    for host in hosts_ports_dict.keys():
        for port in hosts_ports_dict[host].keys():
            card_str = str(hosts_ports_dict[host][port].split('/')[0])
            try:
                result = subprocess.run(
                    ['ssh', '-o', 'StrictHostKeyChecking=no',
                     '-o', 'LogLevel=error',
                     host, '/usr/sbin/ibstat', card_str],
                    capture_output=True, text=True)
                raw_out = result.stdout
            except Exception:
                fatal("There was an issue to query rdma ports on "
                      + host + "\n")
            if 'Ethernet' in raw_out:
                print(RED + "ERROR: " + NOCOLOR +
                      "host " + host + " has Mellanox ports " + port +
                      " on Ethernet mode")
                errors += 1
    return errors


def map_ib_to_mlx(host, rdma_ports_list):
    try:
        result = subprocess.run(
            ['ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'LogLevel=error',
             host, 'ibdev2netdev'],
            capture_output=True, text=True)
    except Exception:
        fatal("There was an issue to query rdma cards on " + host + "\n")

    port_pair_dict = {}
    for line in result.stdout.strip().splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        mlx_name = parts[0]
        port_num = parts[2]
        os_name = parts[4]
        if os_name in rdma_ports_list:
            port_pair_dict[os_name] = '{}/{}'.format(mlx_name, port_num)

    for osdev, ca in port_pair_dict.items():
        print(GREEN + "OK: " + NOCOLOR +
              "on host " + host + " the RDMA port " + osdev + " is CA " + ca)
    return port_pair_dict


def check_rdma_ports_OS(host, port):
    try:
        return_code = subprocess.call(
            ['ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'LogLevel=error',
             host, 'ifconfig', port],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        fatal("cannot check port over ssh on host " + host)
    return return_code != 0


def check_rdma_tools(host, toolpath):
    errors = 0
    rc_tool = ssh_file_exists(host, toolpath)
    if rc_tool == 0:
        print(GREEN + "OK: " + NOCOLOR +
              "on host " + host + " the file " + toolpath + " exists")
    else:
        print(RED + "ERROR: " + NOCOLOR +
              "on host " + host + " the file " + toolpath +
              " does *NOT* exists")
        errors += 1
    return errors


def unique_items_list(my_list):
    return list(dict.fromkeys(my_list))


def create_mlx_csv(hosts_ports_dict, rdma_ports_list):
    mlx_list = [
        hosts_ports_dict[host][os_port]
        for host in hosts_ports_dict
        for os_port in hosts_ports_dict[host]
        if os_port in rdma_ports_list
    ]
    return ','.join(unique_items_list(mlx_list))


def check_rdma_ports(hosts_dictionary, rdma_ports_list):
    fatal_error = False
    for host in hosts_dictionary.keys():
        error_tool_ibdev = check_rdma_tools(host, "ibdev2netdev")
        error_tool_ibstat = check_rdma_tools(host, "ibstat")
    if error_tool_ibdev + error_tool_ibstat > 0:
        fatal("Fix the missing files before running this tool again.\n")

    for host in hosts_dictionary.keys():
        for port in rdma_ports_list:
            if check_rdma_ports_OS(host, port):
                fatal("On host " + str(host) + " port " + port +
                      " not found\n")

    errors_ports = 0
    for host in hosts_dictionary.keys():
        if not ssh_rdma_ports_are_up(host, rdma_ports_list):
            errors_ports += 1
    if errors_ports > 0:
        fatal_error = True

    hosts_ports_dict = {
        host: map_ib_to_mlx(host, rdma_ports_list)
        for host in hosts_dictionary
    }
    rdma_ports_csv_mlx = create_mlx_csv(hosts_ports_dict, rdma_ports_list)
    errors_port_mode = check_rdma_port_mode(hosts_ports_dict)
    if errors_port_mode > 0:
        fatal("Fix the port mode or disconnect the link "
              "before running this tool again.\n")
    return fatal_error, rdma_ports_csv_mlx


def is_IP_address(ip):
    if ip.count('.') != 3:
        return False
    try:
        socket.inet_aton(ip)
        return True
    except Exception:
        fatal("cannot check IP address " + ip + "\n")


def check_hosts_are_ips(hosts_dictionary):
    for host in hosts_dictionary.keys():
        if not is_IP_address(host):
            fatal("on hosts JSON file or CLI parameter '" + host +
                  "' is not a valid IPv4. Fix before running this tool "
                  "again.\n")


def check_hosts_number(hosts_dictionary):
    n = len(hosts_dictionary)
    if n > 64 or n < 2:
        fatal("the number of hosts is not valid. It is " + str(n) +
              " and should be between 2 and 64 unique hosts.\n")


def create_local_log_dir(log_dir_timestamp):
    logdir = Path.cwd() / 'log' / log_dir_timestamp
    try:
        logdir.mkdir(parents=True)
        return str(logdir)
    except Exception:
        fatal("cannot create local directory " + str(logdir) + "\n")


def create_log_dir(hosts_dictionary, log_dir_timestamp):
    print("Creating log dir on hosts:")
    errors = 0
    logdir = str(Path.cwd() / 'log' / log_dir_timestamp)
    for host in hosts_dictionary:
        return_code = subprocess.call(
            ['ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'LogLevel=error',
             host, 'mkdir', '-p', logdir],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if return_code == 0:
            print(GREEN + "OK: " + NOCOLOR +
                  "on host " + host + " logdir " + logdir +
                  " has been created")
        else:
            print(RED + "ERROR: " + NOCOLOR +
                  "on host " + host + " logdir " + logdir +
                  " has *NOT* been created")
            errors += 1
    if errors > 0:
        fatal("we cannot continue without all the log directories created")
    return logdir


def latency_test(hosts_dictionary, logdir, fping_count):
    fping_count_str = str(fping_count)
    hosts_fping = " ".join(sorted(hosts_dictionary.keys()))

    for srchost in sorted(hosts_dictionary.keys()):
        print("")
        print("Starting ping run from " + srchost + " to all nodes")
        fileurl = str(Path(logdir) / ("lat_" + srchost + "_all"))
        command = ("ssh -o StrictHostKeyChecking=no -o LogLevel=error " +
                   srchost + " fping -C " + fping_count_str +
                   " -q -A " + hosts_fping)
        with open(fileurl, 'wb', 0) as logfping:
            runfping = subprocess.Popen(shlex.split(command),
                                        stderr=subprocess.STDOUT,
                                        stdout=logfping)
            runfping.wait()
        print("Ping run from " + srchost + " to all nodes completed")


def throughput_test_os(command, nsd_logfile, client):
    try:
        runperf = subprocess.Popen(shlex.split(command), stdout=nsd_logfile)
        runperf.wait()
        time.sleep(5)
    except Exception:
        fatal("Throughput run " + client + "failed unexpectedly "
              " when calling: " + str(command) + "\n")


def throughput_test(hosts_dictionary, logdir, perf_runtime,
                    rdma_test, rdma_ports_csv_mlx):
    print("")
    print("Starting throughput tests. Please be patient.")
    for client in hosts_dictionary.keys():
        print("")
        print("Starting throughput run from " + client + " to all nodes")
        server_hosts_dictionary = dict(hosts_dictionary)
        del server_hosts_dictionary[client]
        server_csv_str = ",".join(server_hosts_dictionary.keys())
        if rdma_test:
            command = ("./nsdperfTool.py -t read -k 4194304 -b 4194304 "
                       "-R 32 -W 32 -T 32 -d " + logdir + " -s " +
                       server_csv_str + " -c " + client + " -l " +
                       str(perf_runtime) + " -p " + rdma_ports_csv_mlx)
        else:
            command = ("./nsdperfTool.py -t read -k 4194304 -b 4194304 "
                       "-R 256 -W 256 -T 256 -d " + logdir + " -s " +
                       server_csv_str + " -c " + client + " -l " +
                       str(perf_runtime))
        nsd_logfile = open(logdir + "/nsdperfTool_log", "a")
        throughput_test_os(command, nsd_logfile, client)
        nsd_logfile.close()
        try:
            copyfile(logdir + "/nsdperfResult.json",
                     logdir + "/nsd_" + client + ".json")
        except Exception:
            print(YELLOW + "WARNING: " + NOCOLOR +
                  "cannot copy result JSON file")
        print("Completed throughput run from " + client + " to all nodes")

    print("")
    print("Starting many to many nodes throughput test")
    middle_index = int(len(hosts_dictionary) / 2)
    clients_nodes_d = dict(list(hosts_dictionary.items())[middle_index:])
    servers_nodes_d = dict(list(hosts_dictionary.items())[:middle_index])
    clients_csv = ",".join(clients_nodes_d.keys())
    servers_csv = ",".join(servers_nodes_d.keys())
    if rdma_test:
        command = ("./nsdperfTool.py -t read -k 4194304 -b 4194304 "
                   "-R 32 -W 32 -T 32 -d " + logdir + " -s " +
                   servers_csv + " -c " + clients_csv + " -l " +
                   str(perf_runtime) + " -p " + rdma_ports_csv_mlx)
    else:
        command = ("./nsdperfTool.py -t read -k 4194304 -b 4194304 "
                   "-R 256 -W 256 -T 256 -d " + logdir + " -s " +
                   servers_csv + " -c " + clients_csv + " -l " +
                   str(perf_runtime))
    nsd_logfile = open(logdir + "/nsdperfTool_log", "a")
    throughput_test_os(command, nsd_logfile, client)
    nsd_logfile.close()
    try:
        copyfile(logdir + "/nsdperfResult.json", logdir + "/nsd_mess.json")
    except Exception:
        print(YELLOW + "WARNING: " + NOCOLOR + "cannot copy result JSON file")
    print("Completed many to many nodes throughput test")
    return clients_nodes_d


def _parse_latencies(lst):
    if not lst:
        fatal("cannot calculate statistics of empty list\n")
    return [float(x.replace('-', '1000.00')) for x in lst]


def mean_list(lst):
    vals = _parse_latencies(lst)
    return sum(vals) / len(vals)


def max_list(lst):
    return max(_parse_latencies(lst))


def min_list(lst):
    return min(_parse_latencies(lst))


def stddev_list(lst, mean=None):
    vals = _parse_latencies(lst)
    try:
        result = statistics.stdev(vals)
    except statistics.StatisticsError:
        result = 0
    return round(Decimal(result), 2)


def pct_diff_list(bw_str_list):
    try:
        return abs(float(min_list(bw_str_list)) * 100 /
                   float(max_list(bw_str_list)))
    except Exception:
        fatal("cannot calculate mean of bandwidth run")


def file_exists(fileurl):
    if not Path(fileurl).is_file():
        fatal("cannot find file: " + fileurl)


def load_json_files_into_dictionary(json_files_list):
    all_json_dict = {}
    try:
        for json_file in json_files_list:
            with open(json_file, 'r') as f:
                all_json_dict[json_file] = json.load(f)
        return all_json_dict
    except Exception:
        fatal("cannot load JSON file: " + json_file)


def load_throughput_tests(logdir, hosts_dictionary, many2many_clients):
    throughput_dict = {}
    nsd_lat_dict = {}
    nsd_std_dict = {}
    nsd_rxe_dict = {}
    nsd_rxe_m2m_d = {}
    nsd_txe_dict = {}
    nsd_txe_m2m_d = {}
    nsd_rtr_dict = {}
    nsd_rtr_m2m_d = {}
    file_host_dict = {}
    throughput_json_files_list = []

    for host in hosts_dictionary.keys():
        fileurl = logdir + "/nsd_" + host + ".json"
        file_exists(fileurl)
        if json_file_loads(fileurl):
            throughput_json_files_list.append(fileurl)
            file_host_dict[fileurl] = host
        else:
            print(RED + "ERROR: " + NOCOLOR +
                  "cannot load JSON for host " + host +
                  ". We are going to ignore this host on the results")

    mess_file_url = logdir + "/nsd_mess.json"
    if json_file_loads(mess_file_url):
        throughput_json_files_list.append(mess_file_url)
        file_host_dict[mess_file_url] = "all at the same time"
    else:
        print(RED + "ERROR: " + NOCOLOR +
              "cannot load JSON for all at the same time "
              ". We are going to ignore this test on the results")

    if not throughput_json_files_list:
        fatal("cannot load any throughput JSON file")

    nsd_json = load_json_files_into_dictionary(throughput_json_files_list)
    for file in throughput_json_files_list:
        host_key = file_host_dict[file]
        throughput_v = Decimal(nsd_json[file]['throughput(MB/sec)'])
        throughput_dict[host_key] = throughput_v
        n_lt_v = Decimal(nsd_json[file]['networkDelay'][0]['average'])
        nsd_lat_dict[host_key] = n_lt_v
        n_std = Decimal(nsd_json[file]['networkDelay'][0]['standardDeviation'])
        nsd_std_dict[host_key] = n_std
        if host_key == "all at the same time":
            for host in many2many_clients.keys():
                nsd_rxe_m2m_d[host] = Decimal(
                    nsd_json[file]['netData'][host]['rxErrors'])
                nsd_txe_m2m_d[host] = Decimal(
                    nsd_json[file]['netData'][host]['txErrors'])
                nsd_rtr_m2m_d[host] = Decimal(
                    nsd_json[file]['netData'][host]['retransmit'])
        else:
            nsd_rxe_dict[host_key] = Decimal(
                nsd_json[file]['netData'][host_key]['rxErrors'])
            nsd_txe_dict[host_key] = Decimal(
                nsd_json[file]['netData'][host_key]['txErrors'])
            nsd_rtr_dict[host_key] = Decimal(
                nsd_json[file]['netData'][host_key]['retransmit'])

    bw_str_list = [str(throughput_dict[k]) for k in throughput_dict
                   if k != 'all at the same time']
    pc_diff_bw = pct_diff_list(bw_str_list)
    max_bw = max_list(bw_str_list)
    min_bw = min_list(bw_str_list)
    mean_bw = mean_list(bw_str_list)
    stddev_bw = stddev_list(bw_str_list)
    pc_diff_bw = round(pc_diff_bw, 2)
    mean_bw = round(mean_bw, 2)
    return (throughput_dict, nsd_lat_dict, nsd_std_dict, pc_diff_bw, max_bw,
            min_bw, mean_bw, stddev_bw, nsd_rxe_dict, nsd_rxe_m2m_d,
            nsd_txe_dict, nsd_txe_m2m_d, nsd_rtr_dict, nsd_rtr_m2m_d)


def load_multiple_fping(logdir, hosts_dictionary):
    all_fping_dictionary = {}
    all_fping_dictionary_max = {}
    all_fping_dictionary_min = {}
    all_fping_dictionary_stddev = {}

    for srchost in hosts_dictionary.keys():
        fileurl = str(Path(logdir) / ("lat_" + srchost + "_all"))
        file_exists(fileurl)
        mean_all = []
        max_all = []
        min_all = []
        with open(fileurl, 'r') as logfping:
            for rawfping in logfping:
                hostIP = rawfping.split(':')[0].rstrip(' ')
                if srchost == hostIP:
                    continue
                latencies = rawfping.split(':')[1].lstrip(' ').rstrip('\n')
                latencies_list = latencies.split(' ')
                mean_all.append(str(mean_list(latencies_list)))
                max_all.append(max(latencies_list))
                min_all.append(min(latencies_list))
        mean = round(Decimal(mean_list(mean_all)), 2)
        all_fping_dictionary[srchost] = mean
        all_fping_dictionary_max[srchost] = max_list(max_all)
        all_fping_dictionary_min[srchost] = min_list(min_all)
        all_fping_dictionary_stddev[srchost] = stddev_list(mean_all)
    return (all_fping_dictionary, all_fping_dictionary_max,
            all_fping_dictionary_min, all_fping_dictionary_stddev)


def save_throughput_to_csv(logdir, throughput_dict):
    fileurl = str(Path(logdir) / "throughput.csv")
    try:
        with open(fileurl, 'w') as csv_file:
            csv_writer = csv.writer(csv_file)
            csv_writer.writerow(["Host", "Throughput MB/sec"])
            for host in throughput_dict.keys():
                csv_writer.writerow([str(host), int(throughput_dict[host])])
        print(GREEN + "INFO: " + NOCOLOR +
              "CSV file with throughput information can be found at " + fileurl)
    except Exception:
        print(RED + "ERROR: " + NOCOLOR +
              "Cannot write throughput.csv file on " + logdir)
        sys.exit(1)


def nsd_KPI(min_nsd_throughput,
            throughput_dict, nsd_lat_dict, nsd_std_dict,
            pc_diff_bw, max_bw, min_bw, mean_bw, stddev_bw,
            nsd_rxe_dict, nsd_rxe_m2m_d,
            nsd_txe_dict, nsd_txe_m2m_d,
            nsd_rtr_dict, nsd_rtr_m2m_d):
    errors = 0
    print("Results for throughput test ")
    for host in throughput_dict.keys():
        if throughput_dict[host] < min_nsd_throughput:
            errors += 1
            print(RED + "ERROR: " + NOCOLOR +
                  "on host " + host + " the throughput test result is " +
                  str(throughput_dict[host]) +
                  " MB/sec. Which is less than the KPI of " +
                  str(min_nsd_throughput) + " MB/sec")
        else:
            print(GREEN + "OK: " + NOCOLOR +
                  "on host " + host + " the throughput test result is " +
                  str(throughput_dict[host]) +
                  " MB/sec. Which is higher than the KPI of " +
                  str(min_nsd_throughput) + " MB/sec")

    if pc_diff_bw < 79:
        errors += 1
        print(RED + "ERROR: " + NOCOLOR +
              "the difference of throughput between maximum and minimum "
              "values is " + str(abs(100 - pc_diff_bw)) + "%, which is more "
              "than 20% defined on the KPI")
    else:
        print(GREEN + "OK: " + NOCOLOR +
              "the difference of throughput between maximum and minimum "
              "values is " + str(abs(100 - pc_diff_bw)) + "%, which is less "
              "than 20% defined on the KPI")

    print("")
    print("The following metrics are not part of the KPI and "
          "are shown for informational purposes only")
    print(GREEN + "INFO: " + NOCOLOR +
          "The maximum throughput value is " + str(max_bw))
    print(GREEN + "INFO: " + NOCOLOR +
          "The minimum throughput value is " + str(min_bw))
    print(GREEN + "INFO: " + NOCOLOR +
          "The mean throughput value is " + str(mean_bw))
    print(GREEN + "INFO: " + NOCOLOR +
          "The standard deviation throughput value is " + str(stddev_bw))
    for host in nsd_lat_dict.keys():
        print(GREEN + "INFO: " + NOCOLOR +
              "The average NSD latency for " + str(host) + " is " +
              str(nsd_lat_dict[host]) + " msec")
    for host in nsd_std_dict.keys():
        print(GREEN + "INFO: " + NOCOLOR +
              "The standard deviation of NSD latency for " + str(host) +
              " is " + str(nsd_std_dict[host]) + " msec")
    for host in nsd_rxe_dict.keys():
        print(GREEN + "INFO: " + NOCOLOR +
              "The packet Rx error count for throughput test on " +
              str(host) + " is equal to " + str(nsd_rxe_dict[host]) +
              " packet[s]")
    for host in nsd_txe_dict.keys():
        print(GREEN + "INFO: " + NOCOLOR +
              "The packet Tx error count for throughput test on " +
              str(host) + " is equal to " + str(nsd_txe_dict[host]) +
              " packet[s]")
    for host in nsd_rtr_dict.keys():
        print(GREEN + "INFO: " + NOCOLOR +
              "The packet retransmit count for throughput test on " +
              str(host) + " is equal to " + str(nsd_rtr_dict[host]) +
              " packet[s]")

    packets_rxe = sum(nsd_rxe_m2m_d.values())
    print(GREEN + "INFO: " + NOCOLOR +
          "The packet Rx error count for throughput test on many to many"
          " is equal to " + str(packets_rxe) + " packet[s]")
    packets_txe = sum(nsd_txe_m2m_d.values())
    print(GREEN + "INFO: " + NOCOLOR +
          "The packet Tx error count for throughput test on many to many"
          " is equal to " + str(packets_txe) + " packet[s]")
    packets_rtr = sum(nsd_rtr_m2m_d.values())
    print(GREEN + "INFO: " + NOCOLOR +
          "The packet retransmit count for throughput test many to many"
          " is equal to " + str(packets_rtr) + " packet[s]")
    return errors


def fping_KPI(fping_dictionary, fping_dictionary_max, fping_dictionary_min,
              fping_dictionary_stddev, test_string, max_avg_latency,
              max_max_latency, max_stddev_latency, rdma_test):
    errors = 0
    print("Results for ICMP latency test " + test_string + "")
    max_avg_latency_str = str(round(max_avg_latency, 2))
    max_max_latency_str = str(round(max_max_latency, 2))
    max_stddev_latency_str = str(round(max_stddev_latency, 2))
    for host in fping_dictionary.keys():
        if fping_dictionary[host] >= max_avg_latency:
            if rdma_test:
                if fping_dictionary[host] >= 2 * max_avg_latency:
                    errors += 1
                    print(RED + "ERROR: " + NOCOLOR +
                          "on host " + host + " the " + test_string +
                          " average ICMP latency is " +
                          str(fping_dictionary[host]) +
                          " msec. Which is higher than the 2*KPI of " +
                          max_avg_latency_str + " msec")
                else:
                    print(YELLOW + "WARNING: " + NOCOLOR +
                          "on host " + host + " the " + test_string +
                          " average ICMP latency is " +
                          str(fping_dictionary[host]) +
                          " msec. Which is higher than the KPI of " +
                          max_avg_latency_str + " msec")
            else:
                errors += 1
                print(RED + "ERROR: " + NOCOLOR +
                      "on host " + host + " the " + test_string +
                      " average ICMP latency is " +
                      str(fping_dictionary[host]) +
                      " msec. Which is higher than the KPI of " +
                      max_avg_latency_str + " msec")
        else:
            print(GREEN + "OK: " + NOCOLOR +
                  "on host " + host + " the " + test_string +
                  " average ICMP latency is " +
                  str(fping_dictionary[host]) +
                  " msec. Which is lower than the KPI of " +
                  max_avg_latency_str + " msec")

        if fping_dictionary_max[host] >= max_max_latency:
            if rdma_test:
                print(YELLOW + "WARNING: " + NOCOLOR +
                      "on host " + host + " the " + test_string +
                      " maximum ICMP latency is " +
                      str(fping_dictionary_max[host]) +
                      " msec. Which is higher than the KPI of " +
                      max_max_latency_str + " msec")
            else:
                errors += 1
                print(RED + "ERROR: " + NOCOLOR +
                      "on host " + host + " the " + test_string +
                      " maximum ICMP latency is " +
                      str(fping_dictionary_max[host]) +
                      " msec. Which is higher than the KPI of " +
                      max_max_latency_str + " msec")
        else:
            print(GREEN + "OK: " + NOCOLOR +
                  "on host " + host + " the " + test_string +
                  " maximum ICMP latency is " +
                  str(fping_dictionary_max[host]) +
                  " msec. Which is lower than the KPI of " +
                  max_max_latency_str + " msec")

        if fping_dictionary_min[host] >= max_avg_latency:
            if rdma_test:
                print(YELLOW + "WARNING: " + NOCOLOR +
                      "on host " + host + " the " + test_string +
                      " minimum ICMP latency is " +
                      str(fping_dictionary_min[host]) +
                      " msec. Which is higher than the KPI of " +
                      max_avg_latency_str + " msec")
            else:
                errors += 1
                print(RED + "ERROR: " + NOCOLOR +
                      "on host " + host + " the " + test_string +
                      " minimum ICMP latency is " +
                      str(fping_dictionary_min[host]) +
                      " msec. Which is higher than the KPI of " +
                      max_avg_latency_str + " msec")
        else:
            print(GREEN + "OK: " + NOCOLOR +
                  "on host " + host + " the " + test_string +
                  " minimum ICMP latency is " +
                  str(fping_dictionary_min[host]) +
                  " msec. Which is lower than the KPI of " +
                  max_avg_latency_str + " msec")

        if fping_dictionary_stddev[host] >= max_stddev_latency:
            if rdma_test:
                print(YELLOW + "WARNING: " + NOCOLOR +
                      "on host " + host + " the " + test_string +
                      " standard deviation of ICMP latency is " +
                      str(fping_dictionary_stddev[host]) +
                      " msec. Which is higher than the KPI of " +
                      max_stddev_latency_str + " msec")
            else:
                errors += 1
                print(RED + "ERROR: " + NOCOLOR +
                      "on host " + host + " the " + test_string +
                      " standard deviation of ICMP latency is " +
                      str(fping_dictionary_stddev[host]) +
                      " msec. Which is higher than the KPI of " +
                      max_stddev_latency_str + " msec")
        else:
            print(GREEN + "OK: " + NOCOLOR +
                  "on host " + host + " the " + test_string +
                  " standard deviation of ICMP latency is " +
                  str(fping_dictionary_stddev[host]) +
                  " msec. Which is lower than the KPI of " +
                  max_stddev_latency_str + " msec")
        print("")

    return errors


def test_ssh(hosts_dictionary):
    for host in hosts_dictionary.keys():
        try:
            ssh_return_code = subprocess.call(
                ['ssh', '-o StrictHostKeyChecking=no', '-o BatchMode=yes',
                 '-o ConnectTimeout=5', '-o LogLevel=error', host, 'uname'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if ssh_return_code == 0:
                print(GREEN + "OK: " + NOCOLOR +
                      "SSH with node " + host + " works")
            else:
                fatal("cannot run ssh to " + host +
                      ". Please fix this problem before running this tool again")
        except Exception:
            fatal("cannot run ssh to " + host +
                  ". Please fix this problem before running this tool again")

        try:
            ssh_return_code = subprocess.call(
                ['ssh', '-o StrictHostKeyChecking=yes', '-o BatchMode=yes',
                 '-o ConnectTimeout=5', '-o LogLevel=error', host, 'uname'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if ssh_return_code == 0:
                print(GREEN + "OK: " + NOCOLOR +
                      "SSH with node " + host +
                      " works with strict host key checks")
            else:
                fatal("cannot run ssh to " + host +
                      " with strict host key checks. Please fix this problem "
                      "before running this tool again")
        except Exception:
            fatal("cannot run ssh to " + host +
                  " with strict host key checks. Please fix this problem "
                  "before running this tool again")
    print("")


def print_end_summary(a_avg_fp_err, a_nsd_err, lat_kpi_ok,
                      fping_kpi_ok, perf_kpi_ok, perf_rt_ok):
    passed = True
    print("")
    print("The summary of this run:")
    print("")

    if a_avg_fp_err > 0:
        print(RED + "\tThe 1:n ICMP latency test failed " +
              str(a_avg_fp_err) + " time[s]" + NOCOLOR)
        passed = False
    else:
        print(GREEN +
              "\tThe 1:n ICMP average latency was successful in all nodes" +
              NOCOLOR)

    if a_nsd_err > 0:
        print(RED + "\tThe 1:n throughput test failed " +
              str(a_nsd_err) + " time[s]" + NOCOLOR)
        passed = False
    else:
        print(GREEN +
              "\tThe 1:n throughput test was successful in all nodes" +
              NOCOLOR)
    print("")

    if passed:
        print(GREEN + "OK: " + NOCOLOR + "All tests had been passed" + NOCOLOR)
    else:
        print(RED + "ERROR: " + NOCOLOR +
              "All test must be passed to certify the environment "
              "to proceed with the next steps" + NOCOLOR)

    if lat_kpi_ok and fping_kpi_ok and perf_kpi_ok and perf_rt_ok and passed:
        print(GREEN + "OK: " + NOCOLOR +
              "You can proceed with the next steps" + NOCOLOR)
        valid_test = 0
    else:
        print(RED + "ERROR: " + NOCOLOR +
              "This run is not valid to certify the environment. "
              "You cannot proceed with the next steps" + NOCOLOR)
        valid_test = 5
    print("")
    return a_avg_fp_err + a_nsd_err + valid_test


def main():
    fatal_error = check_permission_files()
    if fatal_error:
        fatal("there are files with unexpected permissions or non existing\n")

    max_avg_latency, fping_count, perf_runtime, min_nsd_throughput, \
        cli_hosts, hosts_dictionary, rdma_test, rdma_ports_list, \
        no_rpm_check, save_hosts = parse_arguments()
    max_max_latency = max_avg_latency * 2
    max_stddev_latency = max_avg_latency / 3
    rdma_ports_csv_mlx = []

    os_dictionary = load_json("supported_OS.json")
    packages_dictionary = load_json("packages.json")

    linux_distribution = check_distribution()
    if linux_distribution in ("redhat", "centos", "rocky"):
        redhat8 = check_os_redhat(os_dictionary)
    else:
        fatal("this is not a supported Linux distribution for this tool\n")
    if redhat8:
        packages_rdma_dictionary = load_json("packages_rdma_rh8.json")
    else:
        packages_rdma_dictionary = load_json("packages_rdma.json")

    if not cli_hosts:
        hosts_dictionary = load_json("hosts.json")

    check_hosts_are_ips(hosts_dictionary)
    check_hosts_number(hosts_dictionary)

    json_version = get_json_versions(
        os_dictionary, packages_dictionary, packages_rdma_dictionary)
    estimated_runtime_str = str(
        estimate_runtime(hosts_dictionary, fping_count, perf_runtime))
    show_header(KOET_VERSION, json_version, estimated_runtime_str,
                max_avg_latency, fping_count, min_nsd_throughput, perf_runtime)

    if save_hosts:
        write_json_file_from_dictionary(hosts_dictionary, "hosts.json")

    check_localnode_is_in(hosts_dictionary)
    test_ssh(hosts_dictionary)

    print("Pre-flight generic checks:")
    if no_rpm_check:
        print(YELLOW + "WARNING: " + NOCOLOR +
              "you have disabled RPM checks, things might break")
    else:
        host_packages_check(hosts_dictionary, packages_dictionary)

    firewalld_check(hosts_dictionary)
    check_tcp_port_free(hosts_dictionary, 6668)
    print("")

    if rdma_test:
        print("Pre-flight RDMA checks:")
        if no_rpm_check:
            print(YELLOW + "WARNING: " + NOCOLOR +
                  "you have disabled RPM checks, things might break")
        else:
            host_packages_check(hosts_dictionary, packages_rdma_dictionary)
        rdma_port_error, rdma_ports_csv_mlx = check_rdma_ports(
            hosts_dictionary, rdma_ports_list)
        if not rdma_port_error:
            print(GREEN + "OK: " + NOCOLOR +
                  "all RDMA ports are up on all nodes")
        else:
            fatal("not all RDMA ports are up on all nodes\n")
        print("")

    log_dir_timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    logdir = create_local_log_dir(log_dir_timestamp)
    create_log_dir(hosts_dictionary, log_dir_timestamp)
    latency_test(hosts_dictionary, logdir, fping_count)
    many2many_clients = throughput_test(hosts_dictionary, logdir, perf_runtime,
                                        rdma_test, rdma_ports_csv_mlx)

    all_fping_dictionary, all_fping_dictionary_max, all_fping_dictionary_min, \
        all_fping_dictionary_stddev = load_multiple_fping(logdir,
                                                          hosts_dictionary)
    throughput_dict, nsd_lat_dict, nsd_std_dict, pc_diff_bw, max_bw, min_bw, \
        mean_bw, stddev_bw, nsd_rxe_dict, nsd_rxe_m2m_d, nsd_txe_dict, \
        nsd_txe_m2m_d, nsd_rtr_dict, nsd_rtr_m2m_d = load_throughput_tests(
            logdir, hosts_dictionary, many2many_clients)

    print("")
    all_avg_fping_errors = fping_KPI(
        all_fping_dictionary, all_fping_dictionary_max,
        all_fping_dictionary_min, all_fping_dictionary_stddev,
        "1:n", max_avg_latency, max_max_latency, max_stddev_latency, rdma_test)
    all_nsd_errors = nsd_KPI(
        min_nsd_throughput, throughput_dict, nsd_lat_dict, nsd_std_dict,
        pc_diff_bw, max_bw, min_bw, mean_bw, stddev_bw,
        nsd_rxe_dict, nsd_rxe_m2m_d, nsd_txe_dict, nsd_txe_m2m_d,
        nsd_rtr_dict, nsd_rtr_m2m_d)

    lat_kpi_ok, fping_kpi_ok, perf_kpi_ok, perf_rt_ok = check_kpi_is_ok(
        max_avg_latency, fping_count, min_nsd_throughput, perf_runtime)
    save_throughput_to_csv(logdir, throughput_dict)
    return print_end_summary(all_avg_fping_errors, all_nsd_errors,
                             lat_kpi_ok, fping_kpi_ok, perf_kpi_ok, perf_rt_ok)


if __name__ == '__main__':
    main()
